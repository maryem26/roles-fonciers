"""ce fichier fournit une fonction get_connection() qui ouvre une connexion à notre base PostgreSQL en utilisant l’adresse définie dans config.py"""
import psycopg
from psycopg import Connection

from roles_fonciers.config import DATABASE_URL


def get_connection() -> Connection:
    return psycopg.connect(DATABASE_URL)