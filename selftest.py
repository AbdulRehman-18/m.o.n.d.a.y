"""Run before the demo: python selftest.py"""
import config, llm, tools

assert config.GEMINI_KEY, "Set GEMINI_API_KEY in .env"
jpeg, size = tools.capture()
print("screenshot ok", size, "scale", round(tools.scale, 2))
print("gemini ok:", llm.next_action("Call done with one sentence describing what is on screen.", jpeg, size, []))
print("embeddings ok:", len(llm.embed(["hello"])[0]), "dimensions")
try:
    import camera
    print("camera ok:", len(camera.snap()), "bytes")
except Exception as e:
    print("camera skipped:", e)
print("all good")
