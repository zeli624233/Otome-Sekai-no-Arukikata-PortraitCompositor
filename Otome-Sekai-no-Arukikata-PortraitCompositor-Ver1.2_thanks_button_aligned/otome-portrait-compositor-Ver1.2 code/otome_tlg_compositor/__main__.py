import multiprocessing

from .gui import run_app


if __name__ == "__main__":
    multiprocessing.freeze_support()
    run_app()
