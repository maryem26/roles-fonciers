"""Ce fichier récupère l'adresse de connexion à PostgreSQL depuis les variables d'environnement ou utilise une adresse par défaut pour se connecter à notre base de données locale."""
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://roles:roles_dev_password@localhost:5433/roles",
)

# Number of properties sent to the database in one batch.
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5000"))
