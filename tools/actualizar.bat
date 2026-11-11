@echo off
rem Tarea diaria de PICHUPRONOSTICOS (Programador de tareas de Windows)
cd /d C:\Users\Administrator\Documents\PICHUPRONOSTICOS
set PYTHONIOENCODING=utf-8
python tools\actualizar.py >> tools\actualizar.log 2>&1
