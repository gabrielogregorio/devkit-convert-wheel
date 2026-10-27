"""Unit da lógica da roda (sem janela, sem X11): pétalas, troca de roda e quantas tarefas nascem."""

import shutil
import types
import unittest
from unittest import mock

from amostras import gerar, pasta_temporaria

import conversores as c
import roda_conversor as r


class RodaFalsa:
    def __init__(self):
        self.alvos = []

    def trocar(self, alvos):
        self.alvos = alvos

    def preencher(self, arquivos, alvos, msg):
        self.alvos = alvos

    def mover(self, x, y):
        pass


def app_falso():
    a = r.App.__new__(r.App)
    a.roda = RodaFalsa()
    a.x11 = types.SimpleNamespace(ponteiro=lambda: (0, 0, 0))
    a.cfg = {"ajustes": {}, "pasta_saida": ""}
    return a


class TestRoda(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = pasta_temporaria()
        cls.a = gerar(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def imgs(self):
        return [self.a["vermelha.jpg"], self.a["verde.png"], self.a["azul_alfa.png"]]

    def test_varias_imagens_tem_juntar_na_principal(self):
        app = app_falso()
        app._mostrar_alvos(self.imgs())
        rot = [x.rotulo for x in app.roda.alvos]
        self.assertIn("⧉ JUNTAR", rot)
        self.assertIn("PNG", rot)
        self.assertEqual(rot[-1], "+ MAIS")

    def test_uma_imagem_sem_juntar(self):
        app = app_falso()
        app._mostrar_alvos(self.imgs()[:1])
        self.assertNotIn("⧉ JUNTAR", [x.rotulo for x in app.roda.alvos])

    def test_trocar_pra_juntar_e_voltar(self):
        app = app_falso()
        app._mostrar_alvos(self.imgs())
        principal = [x.rotulo for x in app.roda.alvos]
        juntar = next(x for x in app.roda.alvos if x.rotulo == "⧉ JUNTAR")
        app._trocar_roda(juntar)
        rot = [x.rotulo for x in app.roda.alvos]
        self.assertEqual(rot[0], "LADOS")
        self.assertEqual(rot[-1], "← VOLTAR")
        app._trocar_roda(app.roda.alvos[-1])
        self.assertEqual([x.rotulo for x in app.roda.alvos], principal)

    def test_mais_e_voltar_continuam_funcionando(self):
        app = app_falso()
        app._mostrar_alvos(self.imgs())
        mais = next(x for x in app.roda.alvos if x.rotulo == "+ MAIS")
        app._trocar_roda(mais)
        self.assertIn("AVIF", [x.rotulo for x in app.roda.alvos])

    def test_familias_misturadas_abre_direto_no_juntar(self):
        app = app_falso()
        app._mostrar_alvos([self.a["vermelha.jpg"], self.a["nota.txt"]])
        self.assertEqual([x.rotulo for x in app.roda.alvos], ["ZIP"])

    def test_disparar_junta_cria_uma_tarefa_com_tudo(self):
        app = app_falso()
        alvo = c.achar_alvo(self.imgs(), "juntar:GRADE:montagem")
        with mock.patch.object(r, "TelaTarefa") as tarefa:
            app.disparar(self.imgs(), alvo)
        self.assertEqual(tarefa.call_count, 1)
        _, origens, _, _, destino = tarefa.call_args[0]
        self.assertEqual(origens, self.imgs())
        self.assertTrue(destino.endswith("vermelha - grade montagem.png"))

    def test_disparar_normal_cria_uma_por_arquivo(self):
        app = app_falso()
        alvo = c.alvos_para(self.imgs()[0])[0]
        with mock.patch.object(r, "TelaTarefa") as tarefa:
            app.disparar(self.imgs(), alvo)
        self.assertEqual(tarefa.call_count, 3)
        self.assertTrue(all(len(ch[0][1]) == 1 for ch in tarefa.call_args_list))

    def test_ajustes_lembrados_valem_no_juntar(self):
        app = app_falso()
        alvo = c.achar_alvo(self.imgs(), "juntar:LADOS:lado a lado")
        app.cfg["ajustes"][alvo.chave] = {"espaco": 33}
        with mock.patch.object(r, "TelaTarefa") as tarefa:
            app.disparar(self.imgs(), alvo)
        self.assertEqual(tarefa.call_args[0][3]["espaco"], 33)


if __name__ == "__main__":
    unittest.main()
