# Phase 2 - RAF-DB Improvement

## Problem

The FER2013 model achieved around 82% validation accuracy but struggled on real webcam footage.

Observed issues:
- Subtle emotions were difficult to detect
- Real-world lighting differed from training data
- FER2013 images are low resolution and grayscale

## Solution

Instead of training a new model from scratch, the FER2013 model was further fine-tuned using RAF-DB.

Training pipeline:

ImageNet MobileNetV3
→ Fine-tuned on FER2013
→ Saved as emotion_model.pth
→ Continued training on RAF-DB
→ Saved as emotion_model_raf.pth

## Result

Test Accuracy: ~91%

The webcam predictions became more stable and more realistic.


How to run the new model

1) https://huggingface.co/AD-Nawarathna/Emotion_Detection_FER_2013/resolve/main/emotion_model.pth 


https://huggingface.co/AD-Nawarathna/Emotion_Detection_FER_2013/resolve/main/emotion_model_raf.pth

download both this files 
then run webcam_emotion.py which is in the phase 1