"""Validate a TAS input timeline before starting a replay process."""
import math


def validate(movie):
    if movie.get("format") != "kr-tas-v1":
        raise ValueError("Unsupported movie format")
    end = movie.get("end_frame")
    if isinstance(end, bool) or not isinstance(end, int) or end <= 0:
        raise ValueError("end_frame must be a positive integer")
    if not isinstance(movie.get("events"), list):
        raise ValueError("events must be an array")
    dt = movie.get("dt")
    if not isinstance(dt, (int, float)) or not math.isfinite(dt) or dt <= 0:
        raise ValueError("Invalid timestep")
    names = {"keypressed", "keyreleased", "mousepressed", "mousereleased", "mousemoved", "wheelmoved", "textinput"}
    previous = -1
    for event in movie["events"]:
        frame = event.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int) or not previous <= frame < end or frame < 0:
            raise ValueError("Input frames must be ordered integers before end_frame")
        if event.get("name") not in names or not isinstance(event.get("args"), list):
            raise ValueError("Invalid input event")
        previous = frame
    return movie
