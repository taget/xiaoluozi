import uvicorn


def main() -> None:
    uvicorn.run("xiaoluozi.app:app", host="0.0.0.0", port=8741)


if __name__ == "__main__":
    main()
