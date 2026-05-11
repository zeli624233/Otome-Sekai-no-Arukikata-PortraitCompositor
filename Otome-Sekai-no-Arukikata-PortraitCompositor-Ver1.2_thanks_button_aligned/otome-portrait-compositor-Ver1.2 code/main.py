import multiprocessing

from otome_tlg_compositor.gui import run_app


if __name__ == "__main__":
    multiprocessing.freeze_support()
    run_app()
