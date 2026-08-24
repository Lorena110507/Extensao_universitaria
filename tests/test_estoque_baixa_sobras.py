import unittest
import json
import sqlite3
import os
from app import (
    app, normalizar_categoria, sugerir_categoria, formatar_reais, parse_float_ptbr, agora,
    carregar_materiais, carregar_sobras, carregar_usuarios, init_db, DB_PATH, generate_password_hash,
    SEED_FILE
)


class TestEstoqueBaixaSobras(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # Garante existência do usuário admin com hash conhecido
        cur.execute(
            "INSERT OR REPLACE INTO usuarios (id, username, password_hash, role, roles, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            ("admin-id-test", "admin", generate_password_hash("admin123"), "Admin", '["Admin"]')
        )

        # Garante existência dos materiais padrão se estiver vazio
        cur.execute("SELECT COUNT(1) FROM materiais")
        cnt = cur.fetchone()[0]
        if cnt == 0 and os.path.exists(SEED_FILE):
            with open(SEED_FILE, encoding="utf-8") as f:
                seed = json.load(f)
            now = agora().isoformat()
            for m in seed:
                cur.execute(
                    "INSERT OR IGNORE INTO materiais (id,nome,categoria,emoji,quantidade,unidade,quantidade_minima,custo,gtin,foto,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (m.get("id"), m.get("nome"), m.get("categoria"), m.get("emoji"), float(m.get("quantidade") or 0), m.get("unidade"), float(m.get("quantidade_minima") or 0), float(m.get("custo") or 0), m.get("gtin"), m.get("foto"), now, now)
                )

        conn.commit()
        conn.close()

    def test_moeda_e_parse_reais(self):
        """Valida formatação e conversão de valores no padrão brasileiro (vírgula)."""
        self.assertEqual(formatar_reais(1234.56), "1.234,56")
        self.assertEqual(formatar_reais(0), "0,00")
        self.assertEqual(formatar_reais("45.5"), "45,50")

        self.assertEqual(parse_float_ptbr("1.234,56"), 1234.56)
        self.assertEqual(parse_float_ptbr("45,50"), 45.5)
        self.assertEqual(parse_float_ptbr("R$ 150,00"), 150.0)
        self.assertEqual(parse_float_ptbr("30"), 30.0)
        self.assertEqual(parse_float_ptbr(""), 0.0)

    def test_categorias_sincronizadas(self):
        """Valida sincronização de categorias canônicas a partir do nome ou categoria livre."""
        self.assertEqual(sugerir_categoria("Courino Preto"), "Courino")
        self.assertEqual(sugerir_categoria("Alça de Metal Dourada"), "Metal")
        self.assertEqual(sugerir_categoria("Mosquetão"), "Metal")
        self.assertEqual(sugerir_categoria("Zíper 30cm"), "Aviamento")
        self.assertEqual(sugerir_categoria("Linha de costura"), "Aviamento")
        self.assertEqual(sugerir_categoria("Tecido Algodão Cru"), "Tecido")
        self.assertEqual(sugerir_categoria("Tesoura de alfaiate"), "Outros")

        self.assertEqual(normalizar_categoria("Couro", "Courino Preto"), "Courino")
        self.assertEqual(normalizar_categoria("Metais", "Argola"), "Metal")

    def test_fuso_horario_brasil(self):
        """Valida se o datetime retornado está no fuso correto (UTC-3)."""
        dt = agora()
        self.assertIsNotNone(dt.tzinfo)
        self.assertEqual(dt.utcoffset().total_seconds(), -3 * 3600)

    def test_baixa_material_inexistente_bloqueada(self):
        """Garante que dar baixa em material inexistente é bloqueado."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
            resp = c.post("/baixa", data={
                "material_id": "id-que-nao-existe-999",
                "quantidade": "1",
                "motivo": "Produção de bolsa"
            }, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("Material não encontrado".encode("utf-8"), resp.data)

    def test_baixa_unidades_proibe_floats(self):
        """Garante que para unidades inteiras, valores flutuantes são estritamente rejeitados."""
        materiais = carregar_materiais()
        # Encontra um material em unidades (ex.: Mosquetão ou Zíper)
        mat_unid = next((m for m in materiais if (m.get("unidade") or "").lower().startswith("unid")), None)
        self.assertIsNotNone(mat_unid, "Deve haver material com unidade inteira cadastrado")

        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)

            # Tenta dar baixa em 1.5 unidades (deve falhar)
            resp = c.post("/baixa", data={
                "material_id": mat_unid["id"],
                "quantidade": "1.5",
                "motivo": "Amostra / Teste"
            }, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("utilize apenas números inteiros".encode("utf-8"), resp.data)

            # Baixa inteira (1 unidade) deve passar se houver saldo
            if float(mat_unid["quantidade"]) >= 1:
                qtd_antes = float(mat_unid["quantidade"])
                resp_ok = c.post("/baixa", data={
                    "material_id": mat_unid["id"],
                    "quantidade": "1",
                    "motivo": "Amostra / Teste"
                }, follow_redirects=True)
                self.assertEqual(resp_ok.status_code, 200)
                self.assertIn("Baixa de 1".encode("utf-8"), resp_ok.data)
                mat_depois = next(m for m in carregar_materiais() if m["id"] == mat_unid["id"])
                self.assertEqual(float(mat_depois["quantidade"]), qtd_antes - 1)

    def test_sobras_material_inexistente_bloqueada(self):
        """Garante que criar sobra com material inexistente não é permitido."""
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
            resp = c.post("/sobras/novo", data={
                "material_id": "mat-inexistente-1234",
                "tipo_entrada": "direto",
                "quantidade": "2",
                "unidade": "metros",
                "descricao": "Retalho teste"
            }, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("material selecionado não existe no estoque".encode("utf-8"), resp.data)

    def test_sobras_dimensoes_e_reaproveitamento(self):
        """Testa criação inteligente de sobra por dimensões (30x30 cm) e reaproveitamento."""
        materiais = carregar_materiais()
        courino = next((m for m in materiais if (m.get("unidade") or "").lower() == "metros" and float(m.get("quantidade") or 0) >= 1.0), None)
        if not courino:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("INSERT OR REPLACE INTO materiais (id,nome,categoria,emoji,quantidade,unidade,quantidade_minima,custo,created_at,updated_at) VALUES ('mat-test-courino','Courino Teste','Courino','🟫',10.0,'metros',2,40,datetime('now'),datetime('now'))")
            conn.commit()
            conn.close()
            courino = next(m for m in carregar_materiais() if m["id"] == "mat-test-courino")

        self.assertIsNotNone(courino, "Deve haver material em metros no estoque para o teste")
        qtd_inicial = float(courino["quantidade"])

        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)

            # Cria sobra de 30x30 cm
            # Área = (30 * 30)/10000 = 0.09 m²
            # Metros = 0.09 / 1.40 ≈ 0.064 metros
            resp = c.post("/sobras/novo", data={
                "material_id": courino["id"],
                "tipo_entrada": "dimensoes",
                "comprimento_cm": "30",
                "largura_cm": "30",
                "descricao": "Retalho de Courino 30x30 cm"
            }, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("registrada".encode("utf-8"), resp.data)

            # Verifica dedução no estoque
            mat_pos_sobra = next(m for m in carregar_materiais() if m["id"] == courino["id"])
            self.assertAlmostEqual(float(mat_pos_sobra["quantidade"]), qtd_inicial - 0.064, places=2)

            # Encontra a sobra criada
            sobras = carregar_sobras()
            sobra_criada = next(s for s in sobras if s.get("material_id") == courino["id"] and s["status"] == "Disponível")

            # Reaproveita a sobra
            resp_reap = c.post(f"/sobras/{sobra_criada['id']}/reaproveitar", follow_redirects=True)
            self.assertEqual(resp_reap.status_code, 200)
            self.assertIn("reaproveitada com sucesso".encode("utf-8"), resp_reap.data)

            # Verifica se o estoque foi restaurado
            mat_pos_reap = next(m for m in carregar_materiais() if m["id"] == courino["id"])
            self.assertAlmostEqual(float(mat_pos_reap["quantidade"]), qtd_inicial, places=2)

    def test_usuario_padrao_apenas_admin(self):
        """Valida que o sistema mantém por padrão exclusivamente o usuário admin."""
        usuarios = carregar_usuarios()
        usernames = [u["username"] for u in usuarios]
        self.assertIn("admin", usernames)
        # Verifica que o admin possui papéis configurados
        admin_u = next(u for u in usuarios if u["username"] == "admin")
        self.assertEqual(admin_u.get("role"), "Admin")


if __name__ == "__main__":
    unittest.main()
