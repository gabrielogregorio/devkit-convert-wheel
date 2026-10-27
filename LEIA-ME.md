# Roda Conversora

Segure o **clique da rodinha do mouse** (botão do meio) em cima de um arquivo (Nautilus ou área de trabalho).
Aparece a roda com os formatos.

| Onde soltar | O que acontece |
|---|---|
| Anel de dentro (o formato) | converte direto, mesmo nome, mesma pasta; se existir vira `nome (1).ext` |
| Anel de fora (⚙) | abre os ajustes do formato (qualidade, resolução, corte, páginas, nome, pasta) |
| Centro, ou longe da roda | cancela (nada fica marcado); clique fora só fecha |

Toque rápido no botão deixa a roda aberta: clique esquerdo escolhe, direito cancela.
Pétala **+ MAIS** (dourada) abre a roda de formatos extras: solte/clique nela ou pare o mouse em cima; **← VOLTAR** volta.
Cada conversão mostra uma tela no canto superior direito: barra de progresso, e some sozinha quando termina;
se der erro, fica aberta com o erro com **Como resolver**, detalhes técnicos, **Copiar erro** e **Ajustar e tentar**.

## O que converte

- **Imagem** (png jpg webp avif gif bmp tiff ico heic…): png, jpg, webp, gif, ico, pdf; extras: avif, bmp, tiff; mesmo formato = comprimir; gif/webp animado → mp4/webm
- **SVG**: png, jpg, webp, ico, pdf
- **Áudio**: mp3, wav, ogg, flac, m4a, opus (bitrate, taxa, mono, corte, volume, normalizar)
- **Vídeo**: mp4, mkv, webm, mov, avi, gif, jpg (1 quadro), mp3/wav/m4a (só o áudio); mp4 → mp4 comprimido
- **PDF**: png/jpg por página ou tudo numa imagem só ("1 imagem"), txt, md, docx, PDF comprimido; extras: webp (páginas ou 1 imagem), svg (vetor), tiff multipágina, bmp, html
- **Texto**: txt ↔ md ↔ html, e pdf, docx, odt
- **Office**: docx/odt/rtf, xlsx/ods/csv, pptx/odp → pdf e entre si (LibreOffice)
- **Dados**: json ↔ yaml ↔ csv ↔ tsv, toml → json, e xlsx/ods
- **Legenda**: srt ↔ vtt ↔ ass
- **Fonte**: ttf/otf ↔ woff/woff2
- **Pacote/pasta**: zip ↔ tar.gz/tar.xz/tar.bz2; pasta → zip/tar

## Requisitos

- Ubuntu com GNOME em **X11**, Python 3 do sistema com GTK3 (`python3-gi`, `gir1.2-gtk-3.0`).
- Ícone nativo na barra: `sudo apt install gir1.2-ayatanaappindicator3-0.1` (sem ele cai no ícone legado).
- Conversores: `sudo apt install ffmpeg libreoffice ghostscript poppler-utils python3-pil python3-fitz python3-markdown python3-yaml python3-fonttools python3-brotli`.
  Formato sem a ferramenta instalada só não aparece na roda.

## Vários arquivos de uma vez

Selecione vários e abra a roda: cada formato converte **um por um**, e a pétala **⧉ JUNTAR**
transforma tudo em **um arquivo só**:

| Seleção | Juntar em |
|---|---|
| imagens | LADOS (lado a lado), EMPILHAR, GRADE, MISTURAR (média, sobrepor, clarear, multiplicar, diferença), VÍDEO slideshow, GIF animado, PDF |
| imagens + 1 música | VÍDEO com a música dividida entre as imagens |
| vídeos | UNIR (um depois do outro), LADOS (lado a lado, empilhado ou grade) |
| áudios | UNIR ou MISTURAR |
| PDFs (e imagens) | UNIR |
| qualquer coisa | ZIP |

Anel de fora (⚙) = presets: arranjo, colunas, tamanho, espaço, fundo, resolução (16:9, Reels,
quadrado, 4K), segundos por imagem, fade, ordem (seleção ou nome).

**Botão direito do Nautilus → "Converter para ▸"**: os mesmos formatos, "Juntar os N em um ▸",
"Com ajustes… ▸" e "Abrir a roda…". Precisa de `sudo apt install python3-nautilus` e
`nautilus -q` depois do `./instalar.sh`.

## Comandos

```bash
./instalar.sh            # menu de apps + autostart + Nautilus > Scripts > Converter (roda)
./instalar.sh --remover
./verifica.sh            # testa tudo sem abrir janela
python3 roda_conversor.py arquivo.webp   # abre a roda pra esse arquivo
```

Ícone na barra do topo (colorido = ligada, cinza = desligada): "Ligada", converter arquivo…,
configurações (trocar o botão), log. Não tem "Sair": o ícone fica sempre na barra e no login
a roda sobe desligada.
