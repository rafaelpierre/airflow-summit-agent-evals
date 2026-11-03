"""Seed the local login before Airflow can generate and log a password."""
import json
import os


def main():
    password = os.environ.pop('AIRFLOW_ADMIN_PASSWORD')
    path = os.environ['AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE']
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'admin': password}, stream)
    os.execvp('airflow', ['airflow', 'api-server'])


if __name__ == '__main__':
    main()
