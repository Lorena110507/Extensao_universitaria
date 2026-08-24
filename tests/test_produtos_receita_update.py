import sqlite3
import unittest
from werkzeug.datastructures import MultiDict
from app import (
    app, init_db, DB_PATH, generate_password_hash,
    carregar_produtos, carregar_materiais, USE_SQLITE,
    calcular_produto
)


class TestProdutosReceitaUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM usuarios")
        cur.execute("DELETE FROM roles WHERE is_system=0")

        # Admin user
        now = "2026-08-19T20:00:00"
        cur.execute(
            "INSERT OR REPLACE INTO usuarios (id, username, password_hash, role, roles, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("admin-id-test", "admin_tester", generate_password_hash("pass123"), "Admin", '["Admin"]', now)
        )

        # Producao user (has produtos:update)
        cur.execute(
            "INSERT OR REPLACE INTO usuarios (id, username, password_hash, role, roles, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("prod-user-id", "costureira_maria", generate_password_hash("pass123"), "Producao", '["Producao"]', now)
        )

        # Vendas user (only produtos:read)
        cur.execute(
            "INSERT OR REPLACE INTO usuarios (id, username, password_hash, role, roles, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("vendas-user-id", "vendedor_joao", generate_password_hash("pass123"), "Vendas", '["Vendas"]', now)
        )

        conn.commit()
        conn.close()

    def test_produto_editar_view_and_update(self):
        """Testa o carregamento da página de edição e a atualização bem sucedida dos materiais da receita."""
        produtos = carregar_produtos()
        self.assertTrue(len(produtos) > 0, "Deve haver produtos pré-cadastrados")
        p = produtos[0]
        materiais = carregar_materiais()
        self.assertTrue(len(materiais) >= 2, "Deve haver ao menos 2 materiais cadastrados no estoque")

        mat1 = materiais[0]
        mat2 = materiais[1]

        with app.test_client() as c:
            c.post("/login", data={"username": "admin_tester", "password": "pass123"}, follow_redirects=True)

            # 1. GET tela de edição
            resp_get = c.get(f"/produtos/{p['id']}/editar")
            self.assertEqual(resp_get.status_code, 200)
            self.assertIn("Editar Bolsa / Receita".encode("utf-8"), resp_get.data)
            self.assertIn(p["nome"].encode("utf-8"), resp_get.data)

            # 2. POST alterando materiais da receita
            novo_nome = f"{p['nome']} Premium"
            form_data = MultiDict([
                ("nome", novo_nome),
                ("emoji", "🎒"),
                ("preco_venda", "299,90"),
                ("gtin", "7891112223334"),
                ("estoque_pronto", "5"),
                ("material_id[]", mat1["id"]),
                ("material_qtd[]", "2.5"),
                ("material_id[]", mat2["id"]),
                ("material_qtd[]", "3.0")
            ])
            resp_post = c.post(f"/produtos/{p['id']}/editar", data=form_data, follow_redirects=True)
            self.assertEqual(resp_post.status_code, 200)

            # 3. Verifica persistência
            produtos_atualizados = carregar_produtos()
            p_editado = next((prod for prod in produtos_atualizados if prod["id"] == p["id"]), None)
            self.assertIsNotNone(p_editado)
            self.assertEqual(p_editado["nome"], novo_nome)
            self.assertEqual(p_editado["emoji"], "🎒")
            self.assertAlmostEqual(p_editado["preco_venda"], 299.90, places=2)
            self.assertEqual(p_editado["gtin"], "7891112223334")
            self.assertEqual(p_editado["estoque_pronto"], 5)

            # Verifica receita modificada
            receita = p_editado["receita"]
            self.assertEqual(len(receita), 2)
            self.assertEqual(receita[0]["material_id"], mat1["id"])
            self.assertAlmostEqual(receita[0]["quantidade"], 2.5)
            self.assertEqual(receita[1]["material_id"], mat2["id"])
            self.assertAlmostEqual(receita[1]["quantidade"], 3.0)

            # Verifica recálculo de custo e margem
            mat_map = {m["id"]: m for m in carregar_materiais()}
            p_calc = calcular_produto(p_editado, mat_map)
            custo_esperado = round((mat1["custo"] * 2.5) + (mat2["custo"] * 3.0), 2)
            self.assertEqual(p_calc["custo_estimado"], custo_esperado)
            self.assertEqual(p_calc["margem"], round(299.90 - custo_esperado, 2))

    def test_produto_editar_validacoes(self):
        """Verifica que receita vazia e nome em branco são rejeitados."""
        produtos = carregar_produtos()
        p = produtos[0]

        with app.test_client() as c:
            c.post("/login", data={"username": "admin_tester", "password": "pass123"}, follow_redirects=True)

            # 1. Sem receita (nenhum material)
            form_sem_receita = MultiDict([
                ("nome", "Bolsa Sem Receita"),
                ("emoji", "👜"),
                ("preco_venda", "100.00"),
                ("material_id[]", ""),
                ("material_qtd[]", "0")
            ])
            resp = c.post(f"/produtos/{p['id']}/editar", data=form_sem_receita, follow_redirects=True)
            self.assertIn("Não é possível salvar um produto sem materiais na receita.".encode("utf-8"), resp.data)

            # 2. Sem nome
            form_sem_nome = MultiDict([
                ("nome", ""),
                ("emoji", "👜"),
                ("preco_venda", "100.00"),
                ("material_id[]", "mat-qualquer"),
                ("material_qtd[]", "1.0")
            ])
            resp = c.post(f"/produtos/{p['id']}/editar", data=form_sem_nome, follow_redirects=True)
            self.assertIn("Informe o nome do produto.".encode("utf-8"), resp.data)

    def test_produto_rbac_permissions(self):
        """Valida que o sistema de níveis de acesso (RBAC) protege a rota de edição de produtos e receitas."""
        produtos = carregar_produtos()
        p = produtos[0]

        with app.test_client() as c:
            # 1. Vendedor (sem permissão de update em produtos) -> Bloqueado
            c.post("/login", data={"username": "vendedor_joao", "password": "pass123"}, follow_redirects=True)

            # Tenta GET
            resp_get = c.get(f"/produtos/{p['id']}/editar", follow_redirects=False)
            self.assertEqual(resp_get.status_code, 302, "Usuário sem permissão deve ser redirecionado")

            # Tenta POST
            resp_post = c.post(f"/produtos/{p['id']}/editar", data={"nome": "Hack"}, follow_redirects=False)
            self.assertEqual(resp_post.status_code, 302, "POST sem permissão deve ser redirecionado")

            # 2. Usuário de Produção (com permissão de update em produtos) -> Permitido
            c.post("/login", data={"username": "costureira_maria", "password": "pass123"}, follow_redirects=True)
            resp_get_prod = c.get(f"/produtos/{p['id']}/editar")
            self.assertEqual(resp_get_prod.status_code, 200, "Usuário de produção deve ter acesso")

    def test_ania_assistant_editar_receita_chat(self):
        """Testa a rota de chat do assistente Ania para intenção de alterar materiais da bolsa."""
        produtos = carregar_produtos()
        p = produtos[0]

        with app.test_client() as c:
            # 1. Admin pede para editar materiais da bolsa
            c.post("/login", data={"username": "admin_tester", "password": "pass123"}, follow_redirects=True)
            resp_admin = c.post("/api/ania/chat", json={"message": f"alterar materiais da {p['nome']}"})
            self.assertEqual(resp_admin.status_code, 200)
            data_admin = resp_admin.get_json()
            self.assertIn("Editar Receita", data_admin.get("reply", ""))
            self.assertEqual(data_admin.get("action", {}).get("type"), "navigate")
            self.assertIn(f"/produtos/{p['id']}/editar", data_admin.get("action", {}).get("url", ""))

            # 2. Vendedor (sem permissão produtos:update) pede para editar
            c.post("/login", data={"username": "vendedor_joao", "password": "pass123"}, follow_redirects=True)
            resp_vendedor = c.post("/api/ania/chat", json={"message": f"alterar materiais da {p['nome']}"})
            self.assertEqual(resp_vendedor.status_code, 200)
            data_vendedor = resp_vendedor.get_json()
            self.assertTrue(data_vendedor.get("denied"))
            self.assertIn("Acesso Negado", data_vendedor.get("reply", ""))


if __name__ == "__main__":
    unittest.main()
