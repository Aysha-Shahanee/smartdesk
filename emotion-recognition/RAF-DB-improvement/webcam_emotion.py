import cv2
import torch
import torch.nn as nn
import time
from pathlib import Path
from torchvision import models, transforms
from PIL import Image

from emotion_block_aggregator import EmotionBlockAggregator

# ------------------ DEVICE ------------------
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device:", device)

# ------------------ MODEL ------------------
model = models.mobilenet_v3_small(weights=None)
model.classifier[3] = nn.Linear(model.classifier[3].in_features, 4)

model_path = Path(__file__).with_name("emotion_model_raf.pth")
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
latest_emotion = "Unknown"
aggregator = EmotionBlockAggregator(Path(__file__).with_name("emotion_15min_blocks.jsonl"))

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1
    for block in aggregator.complete_expired_blocks():
        print("Saved 15-minute emotion block:", block)

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
    print("Saved final partial emotion block:", final_block)
cv2.destroyAllWindows()
