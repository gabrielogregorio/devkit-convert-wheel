"""Unit do menu "Converter para ▸" com um Nautilus FALSO.

Nunca use o Nautilus real (gi Nautilus 4.0 / Nautilus.FileInfo) fora do processo do Nautilus:
em 2026-10-27 isso deu segfault no python e o Ubuntu abriu o aviso de erro interno.
"""

import importlib.util
import os
import shutil
import sys
import types
import unittest
from unittest import mock

from amostras import RAIZ, TEM_FFMPEG, gerar, pasta_temporaria


class FakeMenu:
    def __init__(self):
        self.itens = []

    def append_item(self, it):
        self.itens.append(it)


class FakeItem:
    def __init__(self, name, label):
        self.name, self.label, self.sub, self.cb = name, label, None, None

    def set_submenu(self, m):
        self.sub = m

    def connect(self, _sinal, cb, *args):
        self.cb = (cb, args)

    def ativar(self):
        cb, args = self.cb
        cb(self, *args)


class FakeArquivo:
    def __init__(self, caminho, esquema="file"):
        self.caminho, self.esquema = caminho, esquema

    def get_uri_scheme(self):
        return self.esquema

    def get_location(self):
        return types.SimpleNamespace(get_path=lambda: self.caminho)


def carregar_extensao():
    """Importa nautilus/roda_conversor_menu.py com @DIR@ trocado e o Nautilus falso no lugar."""
    import gi
    falso = types.ModuleType("gi.repository.Nautilus")
    falso.MenuProvider, falso.Menu, falso.MenuItem = type("MenuProvider", (), {}), FakeMenu, FakeItem
    import gi.repository
    from gi.repository import GObject  # noqa: F401  (o real; só o Nautilus é falso)
    with open(os.path.join(RAIZ, "nautilus", "roda_conversor_menu.py"), encoding="utf-8") as f:
        fonte = f.read()
    fonte = fonte.replace("@DIR@", RAIZ)
    real = gi.require_version
    with mock.patch.dict(sys.modules, {"gi.repository.Nautilus": falso}), \
            mock.patch.object(gi.repository, "Nautilus", falso, create=True), \
            mock.patch.object(gi, "require_version",
                              lambda ns, v: None if ns == "Nautilus" else real(ns, v)):
        mod = types.ModuleType("roda_conversor_menu_teste")
        exec(compile(fonte, "roda_conversor_menu.py", "exec"), mod.__dict__)
    return mod


class TestMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = pasta_temporaria()
        cls.a = gerar(cls.dir)
        cls.ext = carregar_extensao()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def menu(self, nomes, **kw):
        arqs = [FakeArquivo(self.a[n], **kw) for n in nomes]
        return self.ext.MenuRoda().get_file_items(arqs)

    def filhos(self, item):
        return {i.label: i for i in item.sub.itens}

    def test_imagens_tem_formatos_juntar_ajustes_e_roda(self):
        (raiz,) = self.menu(["vermelha.jpg", "verde.png"])
        self.assertEqual(raiz.label, "Converter para")
        f = self.filhos(raiz)
        self.assertIn("WEBP", f)
        self.assertIn("Juntar os 2 em um", f)
        self.assertIn("Com ajustes…", f)
        self.assertIn("Abrir a roda…", f)
        juntar = self.filhos(f["Juntar os 2 em um"])
        self.assertIn("LADOS (lado a lado)", juntar)
        self.assertIn("GRADE (montagem)", juntar)
        ajustes = self.filhos(f["Com ajustes…"])
        self.assertIn("Juntar: LADOS (lado a lado)", ajustes)

    def test_nomes_unicos(self):
        (raiz,) = self.menu(["vermelha.jpg", "verde.png"])
        nomes = []

        def anda(it):
            nomes.append(it.name)
            for x in (it.sub.itens if it.sub else []):
                anda(x)
        anda(raiz)
        self.assertEqual(len(nomes), len(set(nomes)))

    def test_um_arquivo_sem_juntar(self):
        (raiz,) = self.menu(["vermelha.jpg"])
        self.assertNotIn("Juntar os 1 em um", self.filhos(raiz))

    def test_familias_misturadas_so_juntar(self):
        (raiz,) = self.menu(["vermelha.jpg", "nota.txt"])
        f = self.filhos(raiz)
        self.assertNotIn("WEBP", f)
        self.assertEqual(list(self.filhos(f["Juntar os 2 em um"])), ["ZIP (tudo junto)"])

    def test_clique_chama_a_roda_com_alvo(self):
        (raiz,) = self.menu(["vermelha.jpg", "verde.png"])
        item = self.filhos(self.filhos(raiz)["Juntar os 2 em um"])["GRADE (montagem)"]
        with mock.patch.object(self.ext.subprocess, "Popen") as popen:
            item.ativar()
        cmd = popen.call_args[0][0]
        self.assertEqual(cmd[1], os.path.join(RAIZ, "roda_conversor.py"))
        self.assertEqual(cmd[2], "--alvo=juntar:GRADE:montagem")
        self.assertEqual(cmd[3:], [self.a["vermelha.jpg"], self.a["verde.png"]])

    def test_com_ajustes_passa_flag(self):
        (raiz,) = self.menu(["vermelha.jpg", "verde.png"])
        item = self.filhos(self.filhos(raiz)["Com ajustes…"])["Juntar: GRADE (montagem)"]
        with mock.patch.object(self.ext.subprocess, "Popen") as popen:
            item.ativar()
        self.assertIn("--ajustes", popen.call_args[0][0])

    def test_fora_do_disco_local_nao_mostra(self):
        self.assertEqual(self.menu(["vermelha.jpg"], esquema="sftp"), [])

    def test_selecao_gigante_nao_monta(self):
        arqs = [FakeArquivo(self.a["vermelha.jpg"])] * (self.ext.LIMITE + 1)
        self.assertEqual(self.ext.MenuRoda().get_file_items(arqs), [])

    def test_erro_no_motor_nao_derruba_o_nautilus(self):
        with mock.patch("conversores.alvos_para", side_effect=RuntimeError("quebrou")):
            self.assertEqual(self.menu(["vermelha.jpg", "verde.png"]), [])

    def test_videos(self):
        if not TEM_FFMPEG:
            self.skipTest("sem ffmpeg")
        (raiz,) = self.menu(["v1.mp4", "v2_mudo.mp4"])
        juntar = self.filhos(self.filhos(raiz)["Juntar os 2 em um"])
        self.assertIn("UNIR (um depois do outro)", juntar)


if __name__ == "__main__":
    unittest.main()
