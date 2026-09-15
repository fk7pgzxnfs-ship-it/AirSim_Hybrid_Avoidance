import sys, os
ROOT = r"C:\Users\13631\Documents\GitHub\AirSim_Hybrid_Avoidance\AirSim Hybrid Avoidance_v1"
os.chdir(ROOT); sys.path.insert(0, ROOT)
import web.app as a
a.app.run(host="127.0.0.1", port=8787, debug=False, use_reloader=False, threaded=True)