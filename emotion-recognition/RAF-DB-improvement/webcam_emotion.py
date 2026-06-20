import cv2
import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image
from collections import deque

# ------------------ DEVICE ------------------
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device:", device)

# ------------------ MODEL ------------------
model = models.mobilenet_v3_small(weights=None)
model.classifier[3] = nn.Linear(model.classifier[3].in_features, 4)

model.load_state_dict(torch.load("emotion_model_raf.pth", map_location=device))
model.to(device)
model.eval()

class_names = ["angry", "happy", "neutral", "surprise"]

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

# emotion smoothing buffer
emotion_buffer = deque(maxlen=5)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1

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

        if face.size != 0:
            face_pil = Image.fromarray(cv2.cvtColor(face, cv2.COLOR_BGR2RGB))
            face_tensor = transform(face_pil).unsqueeze(0).to(device)

            with torch.no_grad():
                outputs = model(face_tensor)
                _, pred = torch.max(outputs, 1)
                emotion = class_names[pred.item()]

            # ------------------ SMOOTHING ------------------
            emotion_buffer.append(emotion)
            final_emotion = max(set(emotion_buffer), key=emotion_buffer.count)

            # draw box + label
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(frame, final_emotion, (x, y-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 1,
                        (0, 255, 0), 2)

    cv2.imshow("Emotion Detector (Stable)", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()