"""``python -m hrrr_wind.api [--port 8000] [--host 127.0.0.1]`` starts the web app."""
import argparse

import uvicorn


def main():
    ap = argparse.ArgumentParser(description="Serve the HRRR wind analysis web app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    print(f"Open http://{args.host}:{args.port}/")
    uvicorn.run("hrrr_wind.api.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
