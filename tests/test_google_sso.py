import os
import sys
import unittest
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Testing setup
os.environ["USE_SQLITE"] = "1"
os.environ["FLASK_ENV"] = "testing"

import app


class TestGoogleSSO(unittest.TestCase):
    def setUp(self):
        app.app.config["TESTING"] = True
        app.app.config["WTF_CSRF_ENABLED"] = False
        app.app.secret_key = "test-secret-key-for-sso"
        self.client = app.app.test_client()

        app.init_db()
        conn = sqlite3.connect(app.DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios")
        cur.execute("DELETE FROM configuracoes_sso")
        cur.execute("DELETE FROM audits")

        now = app.agora().isoformat()
        cur.execute(
            """
            INSERT INTO usuarios 
            (id, username, password_hash, role, roles, nome, email, created_at, session_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            ("admin-uid", "admin", app.generate_password_hash("admin123"), "Admin", app.serializar_roles(["Admin"]), "Administrador", "admin@ateliehaiti.com", now)
        )
        conn.commit()
        conn.close()

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin-uid"
            sess["session_version"] = 0

    def test_01_configuracoes_sso_crud(self):
        """Testa salvar e ler configurações de Google SSO."""
        self._login_admin()

        resp = self.client.post("/configuracoes/sso", data={
            "google_client_id": "test-client-id.apps.googleusercontent.com",
            "google_client_secret": "test-secret-12345",
            "ativo": "1",
            "auto_cadastro": "1",
            "papel_padrao": "Producao"
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        cfg = app.obter_configuracoes_sso()
        self.assertEqual(cfg.get("google_client_id"), "test-client-id.apps.googleusercontent.com")
        self.assertEqual(cfg.get("google_client_secret"), "test-secret-12345")
        self.assertEqual(cfg.get("ativo"), 1)
        self.assertEqual(cfg.get("auto_cadastro"), 1)
        self.assertEqual(cfg.get("papel_padrao"), "Producao")

    def test_02_login_page_renders_google_button_when_active(self):
        """Testa se a tela de login exibe o botão do Google quando o SSO está ativo."""
        # Desativado
        app.salvar_configuracoes_sso({"google_client_id": "", "ativo": 0})
        resp1 = self.client.get("/login")
        self.assertNotIn("Entrar com o Google", resp1.data.decode("utf-8"))

        # Ativado
        app.salvar_configuracoes_sso({
            "google_client_id": "client-id-ativo",
            "google_client_secret": "secret",
            "ativo": 1,
            "auto_cadastro": 1
        })
        resp2 = self.client.get("/login")
        self.assertIn("Entrar com o Google", resp2.data.decode("utf-8"))

    def test_03_auth_google_login_flow(self):
        """Testa o início do fluxo OAuth 2.0 e geração de state token."""
        app.salvar_configuracoes_sso({
            "google_client_id": "meu-client-id-123",
            "google_client_secret": "secret",
            "ativo": 1,
            "auto_cadastro": 1
        })

        resp = self.client.get("/auth/google/login")
        self.assertEqual(resp.status_code, 302)
        location = resp.headers.get("Location", "")
        self.assertTrue(location.startswith("https://accounts.google.com/o/oauth2/v2/auth"))
        self.assertIn("client_id=meu-client-id-123", location)
        self.assertIn("response_type=code", location)
        self.assertIn("state=", location)

        # Verifica se o state foi salvo na sessão
        with self.client.session_transaction() as sess:
            self.assertIn("oauth_google_state", sess)

    def test_04_auth_google_callback_invalid_state(self):
        """Testa a rejeição de requisições com state token inválido ou ausente."""
        with self.client.session_transaction() as sess:
            sess["oauth_google_state"] = "state-esperado-correto"

        resp = self.client.get("/auth/google/callback?code=abc&state=state-invalido-forjado", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Falha de valida\u00e7\u00e3o de seguran\u00e7a", resp.data.decode("utf-8"))

    @patch("requests.get")
    @patch("requests.post")
    def test_05_auth_google_callback_existing_user_linked(self, mock_post, mock_get):
        """Testa login de usuário existente cujo e-mail é retornado pelo Google."""
        app.salvar_configuracoes_sso({
            "google_client_id": "google-client-id",
            "google_client_secret": "google-secret",
            "ativo": 1,
            "auto_cadastro": 1
        })

        # Mock token response
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"access_token": "mock-access-token-123"}
        mock_post.return_value = mock_token_resp

        # Mock userinfo response (email existente: admin@ateliehaiti.com)
        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status_code = 200
        mock_userinfo_resp.json.return_value = {
            "sub": "google-sub-9999",
            "email": "admin@ateliehaiti.com",
            "name": "Administrador Google",
            "picture": "https://lh3.googleusercontent.com/a/avatar.jpg"
        }
        mock_get.return_value = mock_userinfo_resp

        with self.client.session_transaction() as sess:
            sess["oauth_google_state"] = "valid-state-token"

        resp = self.client.get("/auth/google/callback?code=valid-code&state=valid-state-token", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Sessão iniciada com o usuário existente
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), "admin-uid")

        # Verifica se vinculou google_id
        admin_user = app.encontrar_usuario_por_email("admin@ateliehaiti.com")
        self.assertEqual(admin_user.get("google_id"), "google-sub-9999")

    @patch("requests.get")
    @patch("requests.post")
    def test_06_auth_google_callback_auto_cadastro_new_user(self, mock_post, mock_get):
        """Testa criação e login automático de novo colaborador via Google."""
        app.salvar_configuracoes_sso({
            "google_client_id": "google-client-id",
            "google_client_secret": "google-secret",
            "ativo": 1,
            "auto_cadastro": 1,
            "papel_padrao": "Estoque"
        })

        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"access_token": "mock-token-456"}
        mock_post.return_value = mock_token_resp

        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status_code = 200
        mock_userinfo_resp.json.return_value = {
            "sub": "google-sub-new-user",
            "email": "carlos.costura@gmail.com",
            "name": "Carlos Costureiro",
            "picture": "https://lh3.googleusercontent.com/carlos.jpg"
        }
        mock_get.return_value = mock_userinfo_resp

        with self.client.session_transaction() as sess:
            sess["oauth_google_state"] = "valid-state-token-new"

        resp = self.client.get("/auth/google/callback?code=code-new&state=valid-state-token-new", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Usuário criado e logado
        carlos = app.encontrar_usuario_por_email("carlos.costura@gmail.com")
        self.assertIsNotNone(carlos)
        self.assertEqual(carlos.get("nome"), "Carlos Costureiro")
        self.assertEqual(carlos.get("google_id"), "google-sub-new-user")
        self.assertIn("Estoque", app.usuario_roles_lista(carlos))

    @patch("requests.get")
    @patch("requests.post")
    def test_07_auth_google_callback_blocked_when_auto_cadastro_disabled(self, mock_post, mock_get):
        """Testa bloqueio de novos e-mails quando o auto-cadastro está desativado."""
        app.salvar_configuracoes_sso({
            "google_client_id": "google-client-id",
            "google_client_secret": "google-secret",
            "ativo": 1,
            "auto_cadastro": 0 # Auto-cadastro DESATIVADO
        })

        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"access_token": "mock-token-789"}
        mock_post.return_value = mock_token_resp

        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status_code = 200
        mock_userinfo_resp.json.return_value = {
            "sub": "google-sub-desconhecido",
            "email": "estranho@gmail.com",
            "name": "Usuario Estranho"
        }
        mock_get.return_value = mock_userinfo_resp

        with self.client.session_transaction() as sess:
            sess["oauth_google_state"] = "valid-state-block"

        resp = self.client.get("/auth/google/callback?code=code-block&state=valid-state-block", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Acesso não autorizado para o e-mail", resp.data.decode("utf-8"))
        self.assertIn("estranho@gmail.com", resp.data.decode("utf-8"))

        # Garante que não criou usuário
        user = app.encontrar_usuario_por_email("estranho@gmail.com")
        self.assertIsNone(user)

    @patch("requests.post")
    def test_08_obter_access_token_gmail_com_refresh(self, mock_post):
        """Testa renovação automática do access_token quando expirado usando o refresh_token."""
        app.salvar_configuracoes_sso({
            "google_client_id": "google-client-id",
            "google_client_secret": "google-secret",
            "ativo": 1
        })

        # Insere usuário com token expirado mas com refresh_token válido
        conn = sqlite3.connect(app.DB_PATH)
        cur = conn.cursor()
        exp_passada = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        cur.execute(
            """
            INSERT INTO usuarios 
            (id, username, password_hash, role, roles, email, google_id, google_refresh_token, google_access_token, google_token_expiry, created_at, session_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            ("user-refresh", "renova.user", "pwd", "Producao", "Producao", "renova@gmail.com", "gid-123", "refresh-token-valido", "token-expirado", exp_passada, app.agora().isoformat())
        )
        conn.commit()
        conn.close()

        # Mock da resposta de renovação do Google
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "novo-access-token-renovado",
            "expires_in": 3600
        }
        mock_post.return_value = mock_resp

        res = app.obter_access_token_gmail_usuario("user-refresh")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("access_token"), "novo-access-token-renovado")

        # Verifica chamada ao endpoint de token
        mock_post.assert_called_with(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": "google-client-id",
                "client_secret": "google-secret",
                "refresh_token": "refresh-token-valido",
                "grant_type": "refresh_token"
            },
            timeout=15
        )


if __name__ == "__main__":
    unittest.main()
