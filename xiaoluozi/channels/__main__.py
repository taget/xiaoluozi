from xiaoluozi.config import account_path, env_path
from xiaoluozi.channels.weixin import run_login


def main() -> None:
    print(run_login(account_path(env_path().parent)), flush=True)


if __name__ == "__main__":
    main()
