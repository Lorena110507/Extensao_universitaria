"""
test_ania_chatbot.py - Testes Automatizados para a Assistente Virtual Ania
Valida permissões RBAC e execução de TODAS as ações do site por voz e digitação.
"""

import os
import json
import sqlite3
import unittest
from app import (
    app, init_db, DB_PATH, generate_password_hash,
    carregar_materiais, carregar_pedidos, carregar_produtos,
    carregar_sobras, carregar_despesas, USE_SQLITE
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
        # Garante que financeiro e relatórios estão bloqueados para ApenasEstoque
        cur.execute("INSERT OR REPLACE INTO role_permissions (role, resource, can_create, can_read, can_update, can_delete) VALUES (?, ?, ?, ?, ?, ?)",
                    ("ApenasEstoque", "financeiro", 0, 0, 0, 0))
        cur.execute("INSERT OR REPLACE INTO role_permissions (role, resource, can_create, can_read, can_update, can_delete) VALUES (?, ?, ?, ?, ?, ?)",
                    ("ApenasEstoque", "relatorios", 0, 0, 0, 0))

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

    def test_gerar_relatorio_pdf_via_ania(self):
        """Testa geração de relatório em PDF através da Ania com autorização."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            resp = c.post("/api/ania/chat", json={"message": "Ania, por favor gerar relatório em PDF"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertIn("PDF Gerado", data["reply"])
            self.assertEqual(data.get("action", {}).get("type"), "download")
            self.assertEqual(data.get("action", {}).get("url"), "/exportar/pdf")

    def test_gerar_relatorio_pdf_bloqueado_sem_permissao(self):
        """Testa se usuário sem permissão de relatórios é barrado ao pedir PDF."""
        with app.test_client() as c:
            c.post("/login", data={"username": "operador_estoque", "password": "op123"}, follow_redirects=True)
            resp = c.post("/api/ania/chat", json={"message": "Gerar relatório em PDF"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("denied"))
            self.assertIn("Acesso Negado", data["reply"])

    def test_gerar_exportacao_excel_via_ania(self):
        """Testa exportação para Excel XLSX pela Ania."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            resp = c.post("/api/ania/chat", json={"message": "Exportar planilha Excel"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("action", {}).get("url"), "/exportar/xlsx")

    def test_mudar_status_pedido_via_ania(self):
        """Testa se a Ania consegue alterar o status de um pedido (ex: Concluir ou Cancelar)."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            
            # Cria pedido primeiro
            c.post("/api/ania/chat", json={"message": "Criar pedido para Roberto Silva de 1 bolsa"})
            
            # Altera status para Concluído
            resp = c.post("/api/ania/chat", json={"message": "Concluir pedido de Roberto Silva"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertIn("Status do Pedido Atualizado", data["reply"])

            pedidos = carregar_pedidos()
            ped = next((p for p in pedidos if "Roberto Silva" in p.get("cliente", "")), None)
            self.assertIsNotNone(ped)
            self.assertEqual(ped["status"], "Concluído")

    def test_cadastrar_novo_material_via_ania(self):
        """Testa criação de novo material de estoque por comando da Ania."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            prompt = "Cadastrar material Linha Encerada Marrom categoria Aviamento com 15 unidades custo 8 reais"
            resp = c.post("/api/ania/chat", json={"message": prompt})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertIn("Novo Material Cadastrado", data["reply"])

            mats = carregar_materiais()
            m = next((mat for mat in mats if "Linha Encerada Marrom" in mat["nome"]), None)
            self.assertIsNotNone(m)
            self.assertEqual(m["categoria"], "Aviamento")
            self.assertEqual(float(m["quantidade"]), 15.0)

    def test_entrada_de_estoque_via_ania(self):
        """Testa reposição/entrada de insumo em estoque existente."""
        materiais = carregar_materiais()
        self.assertTrue(len(materiais) > 0)
        mat = materiais[0]
        qtd_ant = float(mat["quantidade"] or 0)

        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            prompt = f"Dar entrada de 10 unidades em {mat['nome']}"
            resp = c.post("/api/ania/chat", json={"message": prompt})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertIn("Entrada no Estoque Registrada", data["reply"])

            mats_atualizados = carregar_materiais()
            mat_pos = next(m for m in mats_atualizados if m["id"] == mat["id"])
            self.assertAlmostEqual(float(mat_pos["quantidade"]), qtd_ant + 10.0, places=2)

    def test_cadastrar_e_ajustar_bolsa_via_ania(self):
        """Testa cadastro de nova bolsa e ajuste de estoque pronto pela Ania."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            
            # Cadastra bolsa
            resp_cad = c.post("/api/ania/chat", json={"message": "Cadastrar bolsa Mochila Escolar com preco 140 reais"})
            self.assertEqual(resp_cad.status_code, 200)
            data_cad = resp_cad.get_json()
            self.assertTrue(data_cad.get("success"))
            
            # Ajusta peças prontas
            resp_ajuste = c.post("/api/ania/chat", json={"message": "Adicionar 4 pecas prontas na Mochila Escolar"})
            self.assertEqual(resp_ajuste.status_code, 200)
            data_ajuste = resp_ajuste.get_json()
            self.assertTrue(data_ajuste.get("success"))
            self.assertIn("Estoque de Peças Prontas Atualizado", data_ajuste["reply"])

            prods = carregar_produtos()
            p = next((prod for prod in prods if "Mochila Escolar" in prod["nome"]), None)
            self.assertIsNotNone(p)
            self.assertEqual(p["estoque_pronto"], 4)

    def test_cadastrar_despesa_financeira_via_ania(self):
        """Testa lançamento de despesa no financeiro por comando da Ania."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            resp = c.post("/api/ania/chat", json={"message": "Cadastrar despesa de 65 reais com Frete de Insumos categoria Frete"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertIn("Despesa Registrada no Financeiro", data["reply"])

            despesas = carregar_despesas()
            d = next((desp for desp in despesas if "Frete De Insumos" in desp.get("descricao", "") or "Frete de Insumos" in desp.get("descricao", "")), None)
            self.assertIsNotNone(d)
            self.assertEqual(float(d["valor"]), 65.0)

    def test_cadastrar_sobra_via_ania(self):
        """Testa registro de sobra/retalho para reaproveitamento pela Ania."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin_ania", "password": "admin123"}, follow_redirects=True)
            resp = c.post("/api/ania/chat", json={"message": "Cadastrar sobra Retalho Jeans Azul com 2 metros"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertIn("Sobra/Retalho Registrado", data["reply"])

            sobras = carregar_sobras()
            s = next((sob for sob in sobras if "Retalho Jeans Azul" in sob.get("descricao", "")), None)
            self.assertIsNotNone(s)

if __name__ == '__main__':
    unittest.main()
