"""Unit do motor de juntar (conversores.py): quais alvos aparecem e o que cada um gera."""

import os
import shutil
import unittest
import zipfile

from amostras import TEM_FFMPEG, faixas, gerar, pasta_temporaria, sonda

import conversores as c


def abrir(caminho):
    """Imagem carregada e arquivo já fechado (sem ResourceWarning)."""
    from PIL import Image
    with Image.open(caminho) as im:
        im.load()
        return im.copy()


def quadros(caminho):
    from PIL import Image
    with Image.open(caminho) as im:
        return im.n_frames


def rotulos(alvos):
    return [(a.rotulo, a.sub) for a in alvos]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = pasta_temporaria()
        cls.a = gerar(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)  # só a pasta que o próprio teste criou

    def alvo(self, origens, rotulo, sub=None):
        for a in c.alvos_juntar(origens):
            if a.rotulo == rotulo and (sub is None or a.sub == sub):
                return a
        self.fail(f"sem alvo {rotulo}/{sub} para {origens}")

    def rodar(self, origens, alvo, **ajuste):
        op = dict(alvo.padroes(), **ajuste)
        destino = c.destino_juntar(origens, alvo, self.dir)
        final = c.converter(origens, alvo, op, destino, c.Progresso())
        self.assertTrue(os.path.getsize(final) > 0)
        return final

    def imgs(self):
        return [self.a["vermelha.jpg"], self.a["verde.png"], self.a["azul_alfa.png"]]


class TestQuaisAlvos(Base):
    def test_um_arquivo_nao_junta(self):
        self.assertEqual(c.alvos_juntar([self.a["vermelha.jpg"]]), [])

    def test_imagens(self):
        r = rotulos(c.alvos_juntar(self.imgs()))
        for esperado in (("LADOS", "lado a lado"), ("EMPILHAR", "montagem"), ("GRADE", "montagem"),
                         ("MISTURAR", "fundir"), ("VÍDEO", "slideshow"), ("GIF", "animado"),
                         ("PDF", "uma por página"), ("ZIP", "tudo junto")):
            self.assertIn(esperado, r)

    def test_tudo_e_junta_e_chaves_unicas(self):
        alvos = c.alvos_juntar(self.imgs())
        self.assertTrue(all(a.junta for a in alvos))
        self.assertEqual(len({a.chave for a in alvos}), len(alvos))

    def test_imagens_com_uma_musica(self):
        if not TEM_FFMPEG:
            self.skipTest("sem ffmpeg")
        r = rotulos(c.alvos_juntar(self.imgs() + [self.a["s2.mp3"]]))
        self.assertEqual(r, [("VÍDEO", "com música"), ("ZIP", "tudo junto")])

    def test_videos_audios_pdfs(self):
        if not TEM_FFMPEG:
            self.skipTest("sem ffmpeg")
        self.assertEqual(rotulos(c.alvos_juntar([self.a["v1.mp4"], self.a["v2_mudo.mp4"]])),
                         [("UNIR", "um depois do outro"), ("LADOS", "vídeos lado a lado"), ("ZIP", "tudo junto")])
        self.assertEqual(rotulos(c.alvos_juntar([self.a["s1.wav"], self.a["s2.mp3"]])),
                         [("UNIR", "áudios"), ("MISTURAR", "áudios"), ("ZIP", "tudo junto")])
        self.assertIn(("UNIR", "PDFs"), rotulos(c.alvos_juntar([self.a["doc1.pdf"], self.a["vermelha.jpg"]])))

    def test_mistura_sem_relacao_so_zip(self):
        self.assertEqual(rotulos(c.alvos_juntar([self.a["nota.txt"], self.a["pasta"]])), [("ZIP", "tudo junto")])

    def test_achar_alvo(self):
        self.assertEqual(c.achar_alvo(self.imgs(), "juntar:GRADE:montagem").rotulo, "GRADE")
        png = c.alvos_para(self.imgs()[0])[0]
        self.assertEqual(c.achar_alvo(self.imgs(), png.chave).chave, png.chave)
        self.assertIsNone(c.achar_alvo(self.imgs(), "juntar:NAO:existe"))

    def test_destino_nao_sobrescreve(self):
        alvo = self.alvo(self.imgs(), "GRADE")
        d1 = c.destino_juntar(self.imgs(), alvo, self.dir)
        self.assertEqual(os.path.basename(d1), "vermelha - grade montagem.png")
        open(d1, "w").close()
        d2 = c.destino_juntar(self.imgs(), alvo, self.dir)
        self.assertEqual(os.path.basename(d2), "vermelha - grade montagem (1).png")
        os.remove(d1)  # arquivo vazio criado pelo próprio teste


class TestImagens(Base):
    def test_lado_a_lado_mesma_altura(self):
        f = self.rodar(self.imgs(), self.alvo(self.imgs(), "LADOS"), espaco=10)
        im = abrir(f)
        # mediana das alturas (200, 300, 256) = 256; 3 peças + 4 espaços
        self.assertEqual(im.height, 256 + 20)
        self.assertEqual(im.width, round(320 * 256 / 200) + round(200 * 256 / 300) + 256 + 40)

    def test_empilhar_mesma_largura(self):
        f = self.rodar(self.imgs(), self.alvo(self.imgs(), "EMPILHAR"), tamanho=100)
        im = abrir(f)
        self.assertEqual(im.width, 100)
        self.assertEqual(im.height, round(200 * 100 / 320) + round(300 * 100 / 200) + 100)

    def test_grade_colunas(self):
        quatro = self.imgs() + [self.a["logo.svg"]]
        f = self.rodar(quatro, self.alvo(quatro, "GRADE"), colunas=2, tamanho=50)
        im = abrir(f)
        self.assertEqual(im.height, 2 * 50)

    def test_fundo_transparente(self):
        f = self.rodar(self.imgs(), self.alvo(self.imgs(), "LADOS"), espaco=8, fundo="transparente")
        im = abrir(f).convert("RGBA")
        self.assertEqual(im.getpixel((0, 0))[3], 0)

    def test_ordem_por_nome(self):
        f = self.rodar(self.imgs(), self.alvo(self.imgs(), "LADOS"), ordem="nome", tamanho=40)
        # por nome: azul_alfa, verde, vermelha -> primeiro pixel é o azul
        r, g, b, _ = abrir(f).convert("RGBA").getpixel((2, 20))
        self.assertGreater(b, r)

    def test_misturar_todos_os_modos(self):
        alvo = self.alvo(self.imgs(), "MISTURAR")
        for modo in ("media", "sobrepor", "clarear", "multiplicar", "diferenca"):
            with self.subTest(modo=modo):
                f = self.rodar(self.imgs(), alvo, modo=modo)
                self.assertEqual(abrir(f).size, (320, 200))  # tamanho da primeira

    def test_gif_quadros(self):
        f = self.rodar(self.imgs(), self.alvo(self.imgs(), "GIF"), ms=100)
        self.assertEqual(quadros(f), 3)

    def test_pdf_paginas(self):
        import fitz
        f = self.rodar(self.imgs(), self.alvo(self.imgs(), "PDF"))
        with fitz.open(f) as d:
            self.assertEqual(d.page_count, 3)


class TestMidia(Base):
    def setUp(self):
        if not TEM_FFMPEG:
            self.skipTest("sem ffmpeg")

    def test_slideshow_duracao(self):
        f = self.rodar(self.imgs(), self.alvo(self.imgs(), "VÍDEO", "slideshow"),
                       duracao=0.5, fade=0, resolucao="1280x720")
        self.assertAlmostEqual(float(sonda(f, "format=duration")), 1.5, delta=0.2)
        self.assertEqual(sonda(f, "stream=width,height"), "1280,720")

    def test_slideshow_com_musica_divide_a_musica(self):
        sel = self.imgs() + [self.a["s2.mp3"]]
        f = self.rodar(sel, self.alvo(sel, "VÍDEO", "com música"), resolucao="1280x720")
        self.assertEqual(faixas(f), ["audio", "video"])
        self.assertAlmostEqual(float(sonda(f, "format=duration")), 1.5, delta=0.25)

    def test_unir_videos_com_um_mudo(self):
        sel = [self.a["v1.mp4"], self.a["v2_mudo.mp4"]]
        f = self.rodar(sel, self.alvo(sel, "UNIR"))
        self.assertEqual(faixas(f), ["audio", "video"])
        self.assertAlmostEqual(float(sonda(f, "format=duration")), 2.0, delta=0.3)
        self.assertEqual(sonda(f, "stream=width,height").splitlines()[0], "320,240")  # do primeiro

    def test_videos_lado_a_lado_arranjos(self):
        sel = [self.a["v1.mp4"], self.a["v2_mudo.mp4"]]
        alvo = self.alvo(sel, "LADOS", "vídeos lado a lado")
        for layout, esperado in (("horizontal", None), ("vertical", None), ("grade", None)):
            with self.subTest(layout=layout):
                f = self.rodar(sel, alvo, layout=layout, tamanho="480")
                w, h = (int(x) for x in sonda(f, "stream=width,height").splitlines()[0].split(","))
                if layout == "horizontal":
                    self.assertEqual(h, 480)
                    self.assertGreater(w, h)
                elif layout == "vertical":
                    self.assertEqual(w, 480)
                    self.assertGreater(h, w)

    def test_audios_unir_e_misturar(self):
        sel = [self.a["s1.wav"], self.a["s2.mp3"]]
        unir = self.rodar(sel, self.alvo(sel, "UNIR", "áudios"))
        mist = self.rodar(sel, self.alvo(sel, "MISTURAR", "áudios"))
        self.assertAlmostEqual(float(sonda(unir, "format=duration")), 2.5, delta=0.2)
        self.assertAlmostEqual(float(sonda(mist, "format=duration")), 1.5, delta=0.2)


class TestPacotes(Base):
    def test_unir_pdfs_com_imagem(self):
        import fitz
        sel = [self.a["doc1.pdf"], self.a["vermelha.jpg"], self.a["doc2.pdf"]]
        f = self.rodar(sel, self.alvo(sel, "UNIR", "PDFs"))
        with fitz.open(f) as d:
            self.assertEqual(d.page_count, 2 + 1 + 1)
        self.assertEqual([n for n in os.listdir(self.dir) if ".img" in n], [])  # sem temporário largado

    def test_zip_com_pasta(self):
        sel = [self.a["nota.txt"], self.a["pasta"]]
        f = self.rodar(sel, self.alvo(sel, "ZIP"))
        with zipfile.ZipFile(f) as z:
            self.assertEqual(sorted(z.namelist()), ["nota.txt", "pasta/dentro.txt"])


class TestErros(Base):
    def test_arquivo_sumiu(self):
        alvo = self.alvo(self.imgs(), "GRADE")
        with self.assertRaises(c.ErroConversao):
            c.converter(self.imgs() + [os.path.join(self.dir, "nao-existe.png")], alvo, alvo.padroes(),
                        os.path.join(self.dir, "x.png"), c.Progresso())

    def test_cancelar_no_meio(self):
        alvo = self.alvo(self.imgs(), "LADOS")
        p = c.Progresso()
        p.cancelar()
        destino = os.path.join(self.dir, "cancelado.png")
        with self.assertRaises(c.Cancelado):
            c.converter(self.imgs(), alvo, alvo.padroes(), destino, p)
        self.assertFalse(os.path.exists(destino))


if __name__ == "__main__":
    unittest.main()
