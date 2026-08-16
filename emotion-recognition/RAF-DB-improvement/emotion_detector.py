from __future__ import annotations

from pathlib import Path

from emotion_block_aggregator import EMOTIONS
from model_files import ensure_raf_model_file


class WebcamEmotionDetector:
    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.cap = None
        self.cv2 = None
        self.torch = None
        self.model = None
        self.transform = None
        self.face_cascade = None
        self.image_class = None
        self.device = None

    def ensure_model_file(self) -> Path:
        return ensure_raf_model_file(self.project_dir)

    def load_model(self, model_path: Path) -> None:
        import cv2
        import torch
        import torch.nn as nn
        from PIL import Image
        from torchvision import models, transforms

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = models.mobilenet_v3_small(weights=None)
        model.classifier[3] = nn.Linear(model.classifier[3].in_features, 4)
        # weights_only=True keeps torch.load from unpickling arbitrary objects.
        # It became the default in torch 2.6, but requirements allow 2.0+, so
        # pass it explicitly rather than depending on which version resolved.
        state_dict = torch.load(model_path, map_location=device, weights_only=True)
        model.load_state_dict(state_dict)
        model.to(device)
        model.eval()

        self.cv2 = cv2
        self.torch = torch
        self.image_class = Image
        self.device = device
        self.model = model
        self.transform = transforms.Compose(
            [
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
            ]
        )
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def open_camera(self, camera_index: int = 0) -> bool:
        self.cap = self.cv2.VideoCapture(camera_index)
        return bool(self.cap and self.cap.isOpened())

    def read_frame(self):
        return self.cap.read()

    def update_face_box(self, frame, frame_count: int, current_face_box):
        if frame_count % 10 != 0 and current_face_box is not None:
            return current_face_box

        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
        if len(faces) == 0:
            return current_face_box

        faces = sorted(faces, key=lambda face: face[2] * face[3], reverse=True)
        return faces[0]

    def crop_face(self, frame, face_box):
        x, y, w, h = face_box
        return frame[y : y + h, x : x + w]

    def predict_face(self, face) -> dict[str, float]:
        face_pil = self.image_class.fromarray(self.cv2.cvtColor(face, self.cv2.COLOR_BGR2RGB))
        face_tensor = self.transform(face_pil).unsqueeze(0).to(self.device)
        with self.torch.no_grad():
            outputs = self.model(face_tensor)
            probabilities = self.torch.softmax(outputs, dim=1).squeeze(0).cpu().tolist()

        return {emotion: probabilities[index] for index, emotion in enumerate(EMOTIONS)}

    def draw_prediction(self, frame, face_box, latest_emotion: str) -> None:
        x, y, w, h = face_box
        self.cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        self.cv2.putText(
            frame,
            latest_emotion,
            (x, y - 10),
            self.cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )

    def show_frame(self, window_name: str, frame) -> bool:
        self.cv2.imshow(window_name, frame)
        return bool(self.cv2.waitKey(1) & 0xFF == ord("q"))

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def close_windows(self) -> None:
        if self.cv2 is not None:
            self.cv2.destroyAllWindows()
