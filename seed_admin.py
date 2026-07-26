import os
import sys

from app import create_app, db
from app.models.instructor import Instructor


def seed_admin():
    correo = os.getenv('ADSO_ADMIN_EMAIL', 'admin@sena.edu.co').strip().lower()
    password = os.getenv('ADSO_ADMIN_PASSWORD', '')
    nombre = os.getenv('ADSO_ADMIN_NOMBRE', 'Administrador')

    admin = Instructor.query.filter_by(correo=correo).first()
    if admin:
        print(f'Admin ya existe: {correo}')
        return 0

    if not password:
        # Sin password no se crea nada: evita cuentas con credencial por defecto.
        print(
            'ADSO_ADMIN_PASSWORD no definida; se omite la creacion del admin. '
            'Defina la variable y reinicie para crearlo.',
            file=sys.stderr,
        )
        return 0

    if len(password) < 8:
        print('ADSO_ADMIN_PASSWORD debe tener al menos 8 caracteres.', file=sys.stderr)
        return 1

    admin = Instructor(nombre=nombre, correo=correo, rol='admin')
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    print(f'Admin creado: {correo}')
    return 0


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        sys.exit(seed_admin())
