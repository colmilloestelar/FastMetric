import uvicorn

from . import config


def main():
    uvicorn.run("server.app:app", host=config.SERVER_HOST, port=config.SERVER_PORT, reload=False)


if __name__ == "__main__":
    main()