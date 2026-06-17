"""컨테이너 기동 시 자동 실행되는 진입점. 실제 앱 로직으로 교체한다."""
import sys


def main() -> None:
    print(f"Python {sys.version} 컨테이너가 기동되었다.")


if __name__ == "__main__":
    main()
