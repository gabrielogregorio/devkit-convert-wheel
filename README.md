<div align="center">

# Roda Conversora

**Segure a rodinha do mouse sobre um arquivo e escolha o formato numa roda estilo GTA V.**

![Python](https://img.shields.io/badge/Python-3.12-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![GTK](https://img.shields.io/badge/GTK-3-4A86CF?style=for-the-badge&logo=gtk&logoColor=white)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04-E95420?style=for-the-badge&logo=ubuntu&logoColor=white)
![GNOME](https://img.shields.io/badge/GNOME-X11-4A86CF?style=for-the-badge&logo=gnome&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)
![LibreOffice](https://img.shields.io/badge/LibreOffice-18A303?style=for-the-badge&logo=libreoffice&logoColor=white)
![Offline](https://img.shields.io/badge/100%25-local%20e%20offline-555555?style=for-the-badge)

</div>

## Sobre o projeto

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

## Configurar num PC novo

Feito e testado em Ubuntu 24.04 + GNOME + Nautilus. Usa o Python do sistema: nada de pip.

1. Sessão **X11** (Xorg). No Ubuntu 24.04: tela de login → engrenagem no canto → "Ubuntu em Xorg". Em Wayland a janela não fica por cima e o mouse não é capturado.
2. Pacotes (o núcleo e os conversores):
   ```bash
   sudo apt install python3 python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 \
                    libx11-6 libxtst6 libxi6 file \
                    ffmpeg ghostscript poppler-utils libreoffice \
                    python3-pil python3-fitz python3-markdown python3-yaml python3-fonttools python3-brotli \
                    heif-gdk-pixbuf librsvg2-common webp-pixbuf-loader
   ```
   Falta uma ferramenta? Só os formatos dela somem da roda (ex.: sem `libreoffice`, nada de Office).
3. Clonar e instalar:
   ```bash
   git clone <url-do-repo> devkit-roda-conversor
   cd devkit-roda-conversor
   ./instalar.sh        # menu de apps + início no login (sobe desligada) + Nautilus > Scripts
   ./verifica.sh        # tem que terminar em OK (./verifica.sh --office testa o LibreOffice)
   ```
4. Ligar: ícone da roda na barra superior → **Ligada**. Depois, segure o **botão do meio**
   (rodinha) sobre um arquivo no Nautilus ou na área de trabalho. Outro botão:
   ícone → Configurações…

**Fora do repositório:** `~/.config/roda-conversor/config.json` (botão, ajustes lembrados),
`~/.cache/roda-conversor/` (log e ícones), atalhos em `~/.local/share/applications/`,
`~/.config/autostart/` e `~/.local/share/nautilus/scripts/Converter (roda)`.
Mudou a pasta de lugar? Rode `./instalar.sh` de novo.

## Scripts disponíveis

```bash
# Rodar
./roda_conversor.py                 # liga a roda (ícone na barra superior)
./roda_conversor.py --desligado     # só o ícone, como no login
./roda_conversor.py foto.webp       # abre a roda pra esse arquivo
./roda_conversor.py --config        # tela de configurações
ferramentas/subir.sh                # reinicia em 2º plano (log em tmp/app.log)

# Instalar / remover
./instalar.sh
./instalar.sh --remover

# Testar (sem janela: renderiza a roda e converte amostras minúsculas)
./verifica.sh
./verifica.sh --office              # inclui conversões pelo LibreOffice
python3 ferramentas/print_telas.py  # print das telas de tarefa e ajustes
```

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

## Uso

Ícone na barra do topo (colorido = ligada, cinza = desligada): **Ligada**, converter arquivo…,
configurações (trocar o botão), log. Não tem "Sair": o ícone fica sempre na barra e no login a
roda sobe desligada. Fora da roda: Nautilus → botão direito → Scripts → Converter (roda).
