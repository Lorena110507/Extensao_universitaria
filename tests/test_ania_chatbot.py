"""
test_ania_chatbot.py - Testes Automatizados para a Assistente Virtual Ania
Valida permissões RBAC, execução de ações e respostas por texto e voz.
"""

import os
import json
import sqlite3
import unittest
from app import (
    app, init_db, DB_PATH, generate_password_hash,
    carregar_materiais, carregar_pedidos, carregar_produtos, USE_SQLITE
)

class TestAniaChatbot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # Cria usuário Admin (acesso total)
        cur.execute(
            "INSERT OR REPLACE INTO usuarios (id, username, password_hash, role, roles, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            ("admin-ania-test", "admin_ania", generate_password_hash("admin123"), "Admin", '["Admin"]')
        )

        # Cria papel customizado 'ApenasEstoque' com permissão apenas em estoque e baixa
        cur.execute("INSERT OR IGNORE INTO roles (id, name, description, is_system, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                    ("role-est-only", "ApenasEstoque", "Acesso apenas ao estoque", 0))
        
        # Define permissões para ApenasEstoque
        cur.execute("INSERT OR REPLACE INTO role_permissions (role, resource, can_create, can_read, can_update, can_delete) VALUES (?, ?, ?, ?, ?, ?)",
                    ("ApenasEstoque", "estoque", 0, 1, 1, 0))
        cur.execute("INSERT OR REPLACE INTO role_permissions (role, resource, can_create, can_read, can_update, can_delete) VALUES (?, ?, ?, ?, ?, ?)",
                    ("ApenasEstoque", "baixa", 1, 1, 0, 0))
        # Garante que financeiro está bloqueado para ApenasEstoque
        cur.execute("INSERT OR REPLACE INTO role_permissions (role, resource, can_create, can_read, can_update, can_delete) VALUES (?, ?, ?, ?, ?, ?)",
                    ("ApenasEstoque", "financeiro", 0, 0, 0, 0))

        # Cria usuário com papel 'ApenasEstoque'
        cur.execute(
            "INSERT OR REPLACE INTO usuarios (id, username, password_hash, role, roles, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            ("user-est-only", "operador_estoque", generate_password_hash("op123"), "ApenasEstoque", '["ApenasEstoque"]')
        )

        conn.commit()
        conn.close()

    def test_acesso_deslogado_bloqueado(self):
        """Verifica se chamada à API da Ania sem login é rejeitada com 401."""
        with app.test_client() as c:
            resp = c.post("/api/ania/chat", json={"message": "Qual o estoque de couro?"})
            self.assertEqual(resp.status_code, 401)
            data = resp.get_json()
            self.assertTrue(data.get("denied"))

    def test_saudacao_e_ajuda(self):
        """Verifica se mensagem de saudação retorna menu de ajuda e sugestões."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            resp = c.post("/api/ania/chat", json={"message": "Olá Ania, quem é você?"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertIn("Ania", data["reply"])
            self.assertIn("voice_text", data)
            self.assertTrue(len(data.get("suggestions", [])) > 0)

    def test_consulta_minhas_permissoes(self):
        """Verifica se a Ania relata corretamente as permissões ativas do usuário."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            resp = c.post("/api/ania/chat", json={"message": "Quais são as minhas permissões?"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertIn("Admin", data["reply"])
            self.assertIn("Administrador", data["reply"])

    def test_rbac_permissao_negada_financeiro_para_usuario_estoque(self):
        """Testa se usuário sem permissão de financeiro é barrado pela Ania com aviso de acesso negado."""
        with app.test_client() as c:
            c.post("/login", data={"username": "operador_estoque", "password": "op123"}, follow_redirects=True)
            
            # Tenta consultar faturamento/financeiro
            resp = c.post("/api/ania/chat", json={"message": "Qual o faturamento e saldo do financeiro?"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("denied"), "Deveria ter negado o acesso")
            self.assertIn("Acesso Negado", data["reply"])
            self.assertIn("financeiro:read", data["reply"])
            self.assertIn("Acesso negado", data["voice_text"])

    def test_rbac_permissao_concedida_estoque_para_usuario_estoque(self):
        """Testa se o mesmo usuário com papel ApenasEstoque consegue consultar o estoque normalmente."""
        with app.test_client() as c:
            c.post("/login", data={"username": "operador_estoque", "password": "op123"}, follow_redirects=True)
            
            resp = c.post("/api/ania/chat", json={"message": "Quanto temos de estoque de materiais?"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertFalse(data.get("denied", False))
            self.assertIn("Estoque", data["reply"])

    def test_execucao_acao_dar_baixa_via_ania(self):
        """Testa se comando de voz/texto executa baixa de insumos no estoque com sucesso."""
        materiais = carregar_materiais()
        self.assertTrue(len(materiais) > 0)
        mat = materiais[0]
        qtd_inicial = float(mat["quantidade"] or 0)

        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            
            prompt = f"Dar baixa de 1 unidade de {mat['nome']} por costura"
            resp = c.post("/api/ania/chat", json={"message": prompt})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"), f"Falha na resposta: {data}")
            self.assertIn("Baixa Realizada com Sucesso", data["reply"])

            # Verifica se o estoque foi atualizado no banco
            mats_atualizados = carregar_materiais()
            mat_pos = next(m for m in mats_atualizados if m["id"] == mat["id"])
            self.assertAlmostEqual(float(mat_pos["quantidade"]), qtd_inicial - 1.0, places=2)

    def test_execucao_acao_criar_pedido_via_ania(self):
        """Testa se comando cria um novo pedido de cliente com cálculo de valor e status."""
        produtos = carregar_produtos()
        self.assertTrue(len(produtos) > 0)
        prod = produtos[0]

        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            
            prompt = f"Criar pedido para Carlos Eduardo de 1 {prod['nome']}"
            resp = c.post("/api/ania/chat", json={"message": prompt})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertIn("Pedido Registrado com Sucesso", data["reply"])

            pedidos = carregar_pedidos()
            ped = next((p for p in pedidos if "Carlos Eduardo" in p.get("cliente", "")), None)
            self.assertIsNotNone(ped)
            self.assertEqual(ped["produto_nome"], prod["nome"])

    def test_widget_presente_no_template_base(self):
        """Verifica se o botão flutuante e modal da Ania são injetados no base.html para usuários autenticados."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            resp = c.get("/")
            self.assertEqual(resp.status_code, 200)
            html = resp.data.decode("utf-8")
            self.assertIn("ania-fab", html)
            self.assertIn("ania-chat-window", html)
            self.assertIn("ania.js", html)
            self.assertIn("ania.css", html)

if __name__ == '__main__':
    unittest.main()
