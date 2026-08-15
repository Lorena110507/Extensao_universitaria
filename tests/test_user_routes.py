import unittest
import sqlite3
from app import app, DB_PATH, init_db, generate_password_hash


class TestUserRoutes(unittest.TestCase):
    def setUp(self):
        app.testing = True
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios")
        cur.execute("INSERT INTO usuarios (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                    ("admin-id", "admin", generate_password_hash("admin"), "Admin"))
        conn.commit()
        conn.close()

    def test_user_crud_flow(self):
        with app.test_client() as client:
            rv = client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
            self.assertEqual(rv.status_code, 200)

            # Ensure /usuarios page loads
            rv = client.get('/usuarios')
            self.assertEqual(rv.status_code, 200)

            # Create a new user
            rv = client.post('/usuarios/novo', data={'username': 'tester', 'password': 'secret', 'password2': 'secret', 'role': 'Estoque'}, follow_redirects=True)
            self.assertEqual(rv.status_code, 200)

            # Verify user exists in DB
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT id, username, role FROM usuarios WHERE username=?", ('tester',))
            row = cur.fetchone()
            conn.close()
            self.assertIsNotNone(row)
            uid = row[0]
            self.assertEqual(row[2], 'Estoque')

            # Delete the user
            rv = client.post(f'/usuarios/{uid}/excluir', follow_redirects=True)
            self.assertEqual(rv.status_code, 200)

            # Confirm deletion
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT id FROM usuarios WHERE username=?", ('tester',))
            row = cur.fetchone()
            conn.close()
            self.assertIsNone(row)


if __name__ == '__main__':
    unittest.main()
