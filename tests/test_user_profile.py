import unittest
import io
import os
import sqlite3
from app import app, DB_PATH, DATA_DIR, init_db, generate_password_hash, encontrar_usuario_por_username


class TestUserProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios")
        cur.execute(
            "INSERT INTO usuarios (id, username, password_hash, role, nome, avatar, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            ("user-profile-id", "maria_artesa", generate_password_hash("senha_antiga"), "Estoque", "Maria Silva", "")
        )
        conn.commit()
        conn.close()

    def test_update_name_only(self):
        with app.test_client() as c:
            # Login
            c.post('/login', data={'username': 'maria_artesa', 'password': 'senha_antiga'}, follow_redirects=True)

            # Update name to "Maria Silva Santos"
            r = c.post('/minha-conta', data={'nome': 'Maria Silva Santos'}, follow_redirects=True)
            self.assertEqual(r.status_code, 200)

            user = encontrar_usuario_por_username('maria_artesa')
            self.assertEqual(user['nome'], 'Maria Silva Santos')

    def test_upload_and_remove_avatar(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'maria_artesa', 'password': 'senha_antiga'}, follow_redirects=True)

            # Upload fake PNG
            fake_img = (io.BytesIO(b"\x89PNG\r\n\x1a\nfakeimagecontent"), "profile.png")
            r = c.post('/minha-conta', data={
                'nome': 'Maria Silva',
                'avatar': fake_img,
            }, content_type='multipart/form-data', follow_redirects=True)
            self.assertEqual(r.status_code, 200)

            user = encontrar_usuario_por_username('maria_artesa')
            self.assertTrue(user['avatar'].startswith('avatar_user-profile-id'))
            file_path = os.path.join(DATA_DIR, 'uploads', user['avatar'])
            self.assertTrue(os.path.exists(file_path))

            # Remove avatar
            r = c.post('/minha-conta', data={
                'nome': 'Maria Silva',
                'remover_avatar': '1',
            }, follow_redirects=True)
            self.assertEqual(r.status_code, 200)

            user = encontrar_usuario_por_username('maria_artesa')
            self.assertEqual(user['avatar'], '')
            self.assertFalse(os.path.exists(file_path))

    def test_change_password_success(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'maria_artesa', 'password': 'senha_antiga'}, follow_redirects=True)

            # Change password
            r = c.post('/minha-conta', data={
                'nome': 'Maria Silva',
                'current_password': 'senha_antiga',
                'new_password': 'nova_senha_segura123',
                'new_password2': 'nova_senha_segura123',
            }, follow_redirects=True)
            self.assertEqual(r.status_code, 200)

            # Try logging out and logging in with new password
            c.get('/logout', follow_redirects=True)
            r = c.post('/login', data={'username': 'maria_artesa', 'password': 'nova_senha_segura123'}, follow_redirects=True)
            self.assertEqual(r.status_code, 200)
            self.assertIn(b'Maria Silva', r.data)

    def test_change_password_invalid_current_password(self):
        with app.test_client() as c:
            c.post('/login', data={'username': 'maria_artesa', 'password': 'senha_antiga'}, follow_redirects=True)

            # Attempt change with wrong current password
            r = c.post('/minha-conta', data={
                'nome': 'Maria Silva',
                'current_password': 'senha_errada',
                'new_password': 'nova_senha_segura123',
                'new_password2': 'nova_senha_segura123',
            }, follow_redirects=True)
            self.assertEqual(r.status_code, 200)

            # Password should remain unchanged
            c.get('/logout', follow_redirects=True)
            r = c.post('/login', data={'username': 'maria_artesa', 'password': 'senha_antiga'}, follow_redirects=True)
            self.assertEqual(r.status_code, 200)


if __name__ == '__main__':
    unittest.main()
