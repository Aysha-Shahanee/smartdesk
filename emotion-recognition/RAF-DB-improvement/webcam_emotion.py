import time

from emotion_service import EmotionRecognitionService


def main() -> None:
    service = EmotionRecognitionService()
    result = service.start(show_window=True)
    print(result["message"])

    try:
        while service.get_status()["running"]:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping emotion recognition...")
        service.stop()


if __name__ == "__main__":
    main()
