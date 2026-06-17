import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms, models
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt
from tqdm import tqdm
import os

# =========================
# 1. DEVICE (CUDA)
# =========================
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device:", device)

# =========================
# 2. DATA TRANSFORMS
# =========================
transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.5], [0.5])
])

# =========================
# 3. LOAD DATASET
# =========================
train_dataset = datasets.ImageFolder("data/raf/train", transform=transform)
test_dataset = datasets.ImageFolder("data/raf/test", transform=transform)

train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)

print("Classes:", train_dataset.classes)

# =========================
# 4. LOAD BASE MODEL
# =========================
model = models.mobilenet_v3_small(weights=None)
model.classifier[3] = nn.Linear(model.classifier[3].in_features, 4)

# Load your FER trained model
model.load_state_dict(torch.load("emotion_model.pth", map_location=device))

model = model.to(device)

# =========================
# 5. LOSS + OPTIMIZER
# =========================
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=0.0001)

# =========================
# 6. TRAINING STORAGE
# =========================
train_losses = []
train_accs = []
test_accs = []

# =========================
# 7. TRAIN LOOP
# =========================
epochs = 5

for epoch in range(epochs):
    model.train()

    total_loss = 0
    correct = 0
    total = 0

    loop = tqdm(train_loader, desc=f"Epoch {epoch+1}/{epochs}")

    for images, labels in loop:
        images, labels = images.to(device), labels.to(device)

        outputs = model(images)
        loss = criterion(outputs, labels)

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        total_loss += loss.item()

        _, predicted = torch.max(outputs, 1)
        correct += (predicted == labels).sum().item()
        total += labels.size(0)

        loop.set_postfix(loss=loss.item())

    train_acc = correct / total
    train_losses.append(total_loss)
    train_accs.append(train_acc)

    # =========================
    # VALIDATION
    # =========================
    model.eval()
    correct = 0
    total = 0

    with torch.no_grad():
        for images, labels in test_loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)

            _, predicted = torch.max(outputs, 1)
            correct += (predicted == labels).sum().item()
            total += labels.size(0)

    test_acc = correct / total
    test_accs.append(test_acc)

    print(f"Epoch {epoch+1}: Loss={total_loss:.4f}, Train Acc={train_acc:.4f}, Test Acc={test_acc:.4f}")

# =========================
# 8. SAVE MODEL
# =========================
torch.save(model.state_dict(), "emotion_model_raf.pth")
print("Saved model: emotion_model_raf.pth")

# =========================
# 9. PLOT RESULTS
# =========================
plt.plot(train_losses)
plt.title("Training Loss")
plt.show()

plt.plot(train_accs)
plt.title("Training Accuracy")
plt.show()

plt.plot(test_accs)
plt.title("Test Accuracy")
plt.show()