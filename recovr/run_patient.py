"""Dev entry point: run ONLY the patient Pygame app.

    python -m recovr.run_patient

Expects the Flask server to be running (python -m recovr.run_therapist);
if it is not, the patient app just sits on the Waiting screen until it appears.
"""

from recovr.patient_app.patient_main import main

if __name__ == "__main__":
    main()
