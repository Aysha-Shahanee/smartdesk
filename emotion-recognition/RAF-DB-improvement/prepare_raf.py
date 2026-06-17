import os
import shutil

source_root = "RAF-DB/DATASET"
target_root = "data/raf"

mapping = {
    "1": "surprise",
    "4": "happy",
    "6": "angry",
    "7": "neutral"
}

for split in ["train", "test"]:
    for folder_id, emotion in mapping.items():

        src = os.path.join(source_root, split, folder_id)

        dst = os.path.join(
            target_root,
            split,
            emotion
        )

        os.makedirs(dst, exist_ok=True)

        for file in os.listdir(src):

            shutil.copy(
                os.path.join(src, file),
                os.path.join(dst, file)
            )

print("RAF dataset prepared.")