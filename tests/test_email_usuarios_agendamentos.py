import os
import sys
import unittest
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Define testing environment before importing app
os.environ["USE_SQLITE"] = "1"
os.environ["FLASK_ENV"] = "testing"

import app


class TestEmailUsuariosAgendamentos(unittest.TestCase):
    def setUp(self):
        app.app.config["TESTING"] = True
        app.app.config["WTF_CSRF_ENABLED"] = False
        app.app.secret_key = "test-secret-key"
        self.client = app.app.test_client()

        # Configura banco de dados em memória ou arquivo de teste
        app.init_db()
        conn = sqlite3.connect(app.DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios")
        cur.execute("DELETE FROM agendamentos_email")
        cur.execute("DELETE FROM historico_envios_email")
        cur.execute("DELETE FROM role_permissions")
        cur.execute("DELETE FROM roles")

        now = app.agora().isoformat()
        # Cria admin de teste
        cur.execute(
            "INSERT INTO usuarios (id, username, password_hash, role, roles, email, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("admin-uid", "admin", app.generate_password_hash("admin123"), "Admin", app.serializar_roles(["Admin"]), "admin@ateliehaiti.com", now)
        )
        conn.commit()
        conn.close()

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin-uid"
            sess["session_version"] = 0

    def test_01_usuario_cadastro_e_edicao_com_email(self):
        """Testa cadastro de novo usuário com e-mail e posterior edição pelo Admin."""
        self._login_admin()

        # Cadastrar novo usuário com e-mail
        resp = self.client.post("/usuarios/novo", data={
            "username": "maria.costureira",
            "email": "maria@ateliehaiti.com",
            "password": "senha123",
            "password2": "senha123",
            "roles": ["Producao"]
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verificar se foi salvo no banco com o e-mail
        u = app.encontrar_usuario_por_username("maria.costureira")
        self.assertIsNotNone(u)
        self.assertEqual(u.get("email"), "maria@ateliehaiti.com")

        # Editar o e-mail do usuário
        resp_edit = self.client.post(f"/usuarios/{u['id']}/editar", data={
            "email": "maria.nova@ateliehaiti.com",
            "roles": ["Producao", "Estoque"]
        }, follow_redirects=True)
        self.assertEqual(resp_edit.status_code, 200)

        u_edit = app.encontrar_usuario_por_username("maria.costureira")
        self.assertEqual(u_edit.get("email"), "maria.nova@ateliehaiti.com")
        self.assertIn("Estoque", app.usuario_roles_lista(u_edit))

    def test_02_minha_conta_atualizar_email(self):
        """Testa atualização de e-mail pelo próprio usuário logado em Minha Conta."""
        self._login_admin()

        resp = self.client.post("/minha-conta", data={
            "nome": "Administrador Chefe",
            "email": "novo.admin@ateliehaiti.com",
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        u = app.encontrar_usuario_por_username("admin")
        self.assertEqual(u.get("email"), "novo.admin@ateliehaiti.com")
        self.assertEqual(u.get("nome"), "Administrador Chefe")

    def test_03_geradores_de_bytes_relatorios(self):
        """Testa se as funções de geração em memória de PDF e XLSX produzem bytes válidos."""
        pdf_fin = app.gerar_pdf_financeiro_bytes()
        self.assertIsInstance(pdf_fin, bytes)
        self.assertTrue(len(pdf_fin) > 100)
        self.assertTrue(pdf_fin.startswith(b"%PDF"))

        pdf_est = app.gerar_pdf_estoque_baixo_bytes()
        self.assertIsInstance(pdf_est, bytes)
        self.assertTrue(len(pdf_est) > 100)
        self.assertTrue(pdf_est.startswith(b"%PDF"))

        xlsx_bytes = app.gerar_xlsx_completo_bytes()
        self.assertIsInstance(xlsx_bytes, bytes)
        self.assertTrue(len(xlsx_bytes) > 100)
        # XLSX é um arquivo zip, começa com magic bytes PK
        self.assertTrue(xlsx_bytes.startswith(b"PK"))

    def test_04_envio_relatorio_por_email_simulado(self):
        """Testa o endpoint de disparo pontual de relatório em modo simulação (sem token Google)."""
        self._login_admin()

        resp = self.client.post("/relatorios/enviar-email", data={
            "tipo_relatorio": "ambos",
            "destinatarios_usuarios": ["admin@ateliehaiti.com"],
            "destinatarios_extras": "gestao@exemplo.com",
            "assunto": "Balanço Mensal de Teste",
            "mensagem": "Segue o relatório solicitado.",
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verifica histórico de envio
        historico = app.carregar_historico_emails(10)
        self.assertTrue(len(historico) >= 1)
        ultimo = historico[0]
        self.assertIn("admin@ateliehaiti.com", ultimo.get("destinatarios", ""))
        self.assertEqual(ultimo.get("status"), "Simulado")
        self.assertEqual(ultimo.get("tipo_relatorio"), "ambos")

    @patch("requests.post")
    def test_05_envio_relatorio_via_gmail_api_real_mock(self, mock_post):
        """Testa o disparo de relatório com token de acesso Google ativo via Gmail API."""
        self._login_admin()

        # Vincula token do Google ao usuário admin
        conn = sqlite3.connect(app.DB_PATH)
        cur = conn.cursor()
        exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        cur.execute("UPDATE usuarios SET google_access_token=?, google_token_expiry=? WHERE id=?", ("mock-google-token-xyz", exp, "admin-uid"))
        conn.commit()
        conn.close()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "gmail-msg-123"}
        mock_post.return_value = mock_resp

        resp = self.client.post("/relatorios/enviar-email", data={
            "tipo_relatorio": "financeiro_pdf",
            "destinatarios_usuarios": ["colaborador@ateliehaiti.com"],
            "assunto": "Balanço Financeiro Oficial",
            "mensagem": "Segue balanço enviado via Gmail API.",
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verifica chamada mock do Gmail endpoint
        mock_post.assert_called()
        call_args, call_kwargs = mock_post.call_args
        self.assertEqual(call_args[0], "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
        self.assertIn("Authorization", call_kwargs.get("headers", {}))
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer mock-google-token-xyz")

        # Verifica histórico com status Sucesso
        historico = app.carregar_historico_emails(1)
        self.assertEqual(historico[0].get("status"), "Sucesso")

    def test_06_agendamento_regular_crud_e_calculo_proximo_envio(self):
        """Testa criação, edição, pausa e exclusão de agendamentos regulares de e-mail."""
        self._login_admin()

        # 1. Criação
        resp = self.client.post("/relatorios/agendamentos/novo", data={
            "titulo": "Relatório Semanal de Segunda",
            "tipo_relatorio": "financeiro_pdf",
            "frequencia": "semanal",
            "hora_envio": "09:00",
            "dia_semana": "0", # Segunda
            "destinatarios_usuarios": ["admin@ateliehaiti.com"],
            "assunto": "Balanço Semanal",
            "ativo": "1"
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        agendamentos = app.carregar_agendamentos_email()
        self.assertEqual(len(agendamentos), 1)
        ag = agendamentos[0]
        self.assertEqual(ag.get("titulo"), "Relatório Semanal de Segunda")
        self.assertEqual(ag.get("ativo"), 1)
        self.assertEqual(ag.get("usuario_remetente_id"), "admin-uid")
        self.assertIsNotNone(ag.get("proximo_envio"))

        # 2. Toggle status (Pausar)
        resp_toggle = self.client.post(f"/relatorios/agendamentos/{ag['id']}/toggle", follow_redirects=True)
        self.assertEqual(resp_toggle.status_code, 200)
        ag_pausado = app.carregar_agendamento_por_id(ag["id"])
        self.assertEqual(ag_pausado.get("ativo"), 0)

        # 3. Edição
        resp_edit = self.client.post(f"/relatorios/agendamentos/{ag['id']}/editar", data={
            "titulo": "Relatório Mensal Atualizado",
            "tipo_relatorio": "completo_xlsx",
            "frequencia": "mensal",
            "hora_envio": "10:30",
            "dia_mes": "15",
            "destinatarios_usuarios": ["admin@ateliehaiti.com"],
            "ativo": "1"
        }, follow_redirects=True)
        self.assertEqual(resp_edit.status_code, 200)
        ag_atualizado = app.carregar_agendamento_por_id(ag["id"])
        self.assertEqual(ag_atualizado.get("titulo"), "Relatório Mensal Atualizado")
        self.assertEqual(ag_atualizado.get("frequencia"), "mensal")
        self.assertEqual(ag_atualizado.get("dia_mes"), 15)

        # 4. Execução Manual ("Enviar Agora")
        resp_exec = self.client.post(f"/relatorios/agendamentos/{ag['id']}/executar", follow_redirects=True)
        self.assertEqual(resp_exec.status_code, 200)

        # 5. Exclusão
        resp_del = self.client.post(f"/relatorios/agendamentos/{ag['id']}/excluir", follow_redirects=True)
        self.assertEqual(resp_del.status_code, 200)
        self.assertEqual(len(app.carregar_agendamentos_email()), 0)

    def test_07_calculo_proximo_envio_frequencias(self):
        """Testa o cálculo do próximo envio para frequências diária, semanal e mensal."""
        base = datetime(2026, 8, 21, 10, 0, 0, tzinfo=app.FUSO_BR) # Sexta-feira às 10:00

        # Diário às 08:00 (já passou hoje, deve ser amanhã às 08:00)
        prox_diario = app.calcular_proximo_envio("diario", "08:00", a_partir_de=base)
        self.assertEqual(prox_diario.day, 22)
        self.assertEqual(prox_diario.hour, 8)

        # Semanal na Segunda-feira (dia_semana=0) às 09:00 (deve ser próxima segunda, dia 24)
        prox_semanal = app.calcular_proximo_envio("semanal", "09:00", dia_semana=0, a_partir_de=base)
        self.assertEqual(prox_semanal.weekday(), 0)
        self.assertEqual(prox_semanal.day, 24)
        self.assertEqual(prox_semanal.hour, 9)

        # Mensal no dia 15 (já passou neste mês dia 15/08, deve ser dia 15/09)
        prox_mensal = app.calcular_proximo_envio("mensal", "08:00", dia_mes=15, a_partir_de=base)
        self.assertEqual(prox_mensal.month, 9)
        self.assertEqual(prox_mensal.day, 15)
        self.assertEqual(prox_mensal.hour, 8)

    def test_08_configuracoes_email_redirect_e_teste(self):
        """Testa redirecionamento de /configuracoes/email para SSO e disparo de teste."""
        self._login_admin()

        resp_get = self.client.get("/configuracoes/email", follow_redirects=False)
        self.assertEqual(resp_get.status_code, 302)
        self.assertIn("/configuracoes/sso", resp_get.headers.get("Location", ""))

        # Disparo de teste
        resp_test = self.client.post("/configuracoes/email/testar", data={
            "email_teste": "teste@exemplo.com"
        }, follow_redirects=True)
        self.assertEqual(resp_test.status_code, 200)


if __name__ == "__main__":
    unittest.main()
