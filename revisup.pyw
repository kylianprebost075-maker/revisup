"""Lance le tableau de bord RevisUP sans fenêtre (démarrage de Windows) : pythonw revisup.pyw"""
import runpy
import sys

sys.argv = ["revisup", "web"]
runpy.run_module("revisup", run_name="__main__", alter_sys=True)
