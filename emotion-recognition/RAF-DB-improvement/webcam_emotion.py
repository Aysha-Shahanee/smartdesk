import cv2
import torch
import torch.nn as nn
import time
from pathlib import Path
from torchvision import models, transforms
from PIL import Image
from dotenv import load_dotenv

from emotion_block_aggregator import EmotionBlockAggregator
from model_files import ensure_raf_model_file
from storage.local_storage import LocalEmotionStorage
from storage.session_manager import SessionManager
from storage.supabase_sync import SupabaseEmotionSync


SYNC_RETRY_SECONDS = 300
OUTPUT_PATH = Path(__file__).with_name("emotion_15min_blocks.jsonl")
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

load_dotenv(ENV_PATH)


session_manager = SessionManager(user_id="local_user")
local_storage = LocalEmotionStorage(OUTPUT_PATH)
sync_client = SupabaseEmotionSync(local_storage)
local_storage.cleanup_old_records()

if sync_client.is_configured:
    synced_count = sync_client.retry_unsynced()
    print(f"Synced {synced_count} pending emotion blocks.")
else:
    print(f"Supabase sync disabled: {sync_client.disabled_reason}")

# ------------------ DEVICE ------------------
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device:", device)

# ------------------ MODEL ------------------
model = models.mobilenet_v3_small(weights=None)
model.classifier[3] = nn.Linear(model.classifier[3].in_features, 4)

model_path = ensure_raf_model_file(Path(__file__).parent)
model.load_state_dict(torch.load(model_path, map_location=device))
model.to(device)
model.eval()

class_names = ["Angry", "Happy", "Neutral", "Surprise"]

# ------------------ FACE DETECTOR ------------------
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

# ------------------ TRANSFORM ------------------
transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.5, 0.5, 0.5],
                         [0.5, 0.5, 0.5])
])

# ------------------ VIDEO ------------------
cap = cv2.VideoCapture(0)

frame_count = 0
face_box = None
last_processed_at = 0.0
last_sync_retry_at = time.monotonic()
latest_emotion = "Unknown"
aggregator = EmotionBlockAggregator(
    output_path=OUTPUT_PATH,
    session_manager=session_manager,
    storage=local_storage,
)


def sync_blocks(blocks: list[dict]) -> None:
    if not sync_client.is_configured:
        return

    for block in blocks:
        sync_client.upload_record(block)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1
    completed_blocks = aggregator.complete_expired_blocks()
    sync_blocks(completed_blocks)
    for block in completed_blocks:
        print("Saved 15-minute emotion block:", block)

    now_monotonic = time.monotonic()
    if now_monotonic - last_sync_retry_at >= SYNC_RETRY_SECONDS:
        last_sync_retry_at = now_monotonic
        local_storage.cleanup_old_records()
        synced_count = sync_client.retry_unsynced()
        if synced_count:
            print(f"Synced {synced_count} pending emotion blocks.")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # ------------------ DETECT FACE (every 10 frames) ------------------
    if frame_count % 10 == 0 or face_box is None:
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5
        )

        if len(faces) > 0:
            # pick largest face (important stability fix)
            faces = sorted(faces, key=lambda x: x[2] * x[3], reverse=True)
            face_box = faces[0]

    # ------------------ USE LAST KNOWN FACE ------------------
    if face_box is not None:
        x, y, w, h = face_box
        face = frame[y:y+h, x:x+w]

        now = time.monotonic()
        should_process_frame = now - last_processed_at >= 1.0

        if face.size != 0 and should_process_frame:
            last_processed_at = now
            face_pil = Image.fromarray(cv2.cvtColor(face, cv2.COLOR_BGR2RGB))
            face_tensor = transform(face_pil).unsqueeze(0).to(device)

            with torch.no_grad():
                outputs = model(face_tensor)
                probabilities = torch.softmax(outputs, dim=1).squeeze(0).cpu().tolist()

            emotion_probabilities = {
                class_name: probabilities[index]
                for index, class_name in enumerate(class_names)
            }
            latest_emotion = max(emotion_probabilities, key=emotion_probabilities.get)
            completed_blocks = aggregator.add_frame(emotion_probabilities)
            sync_blocks(completed_blocks)

            for block in completed_blocks:
                print("Saved 15-minute emotion block:", block)

            # draw box + label
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(frame, latest_emotion, (x, y-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 1,
                    (0, 255, 0), 2)

    cv2.imshow("Emotion Detector (Stable)", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
final_block = aggregator.flush()
if final_block is not None:
    sync_blocks([final_block])
    print("Saved final partial emotion block:", final_block)
local_storage.cleanup_old_records()
synced_count = sync_client.retry_unsynced()
if synced_count:
    print(f"Synced {synced_count} pending emotion blocks.")
cv2.destroyAllWindows()
