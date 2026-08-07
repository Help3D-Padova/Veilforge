https://github.com/Kephren89/Veilforge

L'emplacement du projet est D:\_JDR_Ressources\Veilforge 2.8.0. Reprend le contexte de la dernière fois.
Prépare moi un répertoire propre pour l'uploader sur Github.

documente les modifications que tu as faites partout où c'est nécessaire (code, change log, user guide, etc...) et reconstruit l’exécutable


- lecture fichiers mp4, mkv et WebM avec downscalling si fichier trop gros.
- Possibilité d'ajouter la grille sur un fichier vidéo
- bouton fog : On et Off (automatiquement en Off avec une lecture de fichier vidéo)
- activer par défaut la grille en square
- importer des tokens en jpg ou png, et possibilité de les déplacer, redimensionner, orienter. On peut aussi copier-coller un token, Undo, Redo.
- sauvegarde des tokens avec la map
- importer des tokens sur une map animée.
- demande l'emplacement des images si elles ne sont pas trouvées
- apparition de barres de défilement bas/droite lorsque le zoom de la carte sur l'écrand u master dépasse les 100%
- enlever le code mort
- Correction de comportement pour les tokens : lorsque 2 tokens sont très proches, seuls handles du token séléctionné sont activés.
- Lors de l'import d'un token, redimensionnement  sa taille pour qu'il fasse 5% de la taille de la carte.
- Surbrillance du token séléctionné
- imports multiples tokens
- lorsqu'on va chercher un fichier ou une session, parmis les fichiers disponibles dans l'interface de recherche, il doit y avoir les .json.
- Bouton Parameters qui ouvre une interface avec différents paramètres modifiables (assures-toi que les valeurs positionnées dans les paramètres sont bien prises en compte dans les différentes fonctionnalités) : 
	- chemin par défaut pour aller chercher les maps
	- chemin par défaut pour aller chercher les vidéos
	- chemin par défaut pour aller chercher les tokens
	- choix par défaut du type de Grid lorsqu'on coche la case Grid
	- chemin par défaut pour Save/Load Session


À partir de cette version 2.7.0, est-ce que c'est compliqué de faire une version pouvant être utilisée sur un téléphone portable Android ?


Windows+R
Powershell
cd "D:\_JDR_Ressources\Veilforge 2.8.0\Veilforge-main"
python main.py


une harmonisation terminologique stricte FR sur tout le produit (ex: choisir partout carte ou map, session ou partie, etc.) pour une cohérence éditoriale totale.
__________________________________

Good evening Andrea,
I downloaded Veilforge 2.6.0, and it’s exactly what I was looking for! Thanks a lot for your work and for sharing this application!
Since I wanted to see a few new features implemented — and I’m not a developer at all — I installed Visual Studio Code, used your code as a starting point, and created a version 2.7.0 with nothing but Visual Studio Code's AI assistance (Copilot) in Chat mode.
This allowed me to add the following features:
- Video file playback (mp4, mkv, and WebM) for animated maps, including downscaling for large video files.
- Grid overlay on the video file.
- Square grid enabled by default.
- Ability to import JPG or PNG tokens, + functions to move, resize, rotate, delete  them, + copy-paste functionality.
- Vertical and horizontal scrollbars appear when the map zoom level on the GM's screen exceeds 100%.

I tested my version during a RPG session this afternoon, and everything works well. There are still a few improvements to be made, but core functionalities are there.

I am currently reworking the interface to give it a more modern look.

Would you like to see my version? Could I upload it to your GitHub to share it with the community ?

Best regards,

Cedric

__________________________

**Video / Audio maps**
- You can now open video or audio files directly as the map source.
- Supported formats include MP4, WEBM, MKV, and M4A.
- When a video file is loaded, playback starts automatically and loops on the DM canvas and player screen.
- **Grid on video** is supported: if Grid is enabled, the overlay is drawn on video for both **DM** and **Player** views.

Video playback limitations and stability notes
- Very heavy videos (especially **4K** and/or high bitrate files) can overload some systems and cause UI stalls.
- If this happens, Windows may briefly show **"Not responding"** while decoding catches up.

Veilforge mitigation behavior:
- Detects likely heavy files and shows an informational warning (size + 4K hints, and codec/resolution metadata when available).
- Automatically enables a **lite playback profile** (reduced frame processing and stronger downscale).
- Practical recommendation: For best reliability on modest hardware, prefer 1080p sources or pre-encoded lighter versions of very large maps.


**Import token images**
(Tokens are image markers placed on top of the map (creatures, NPCs, props, effects).
Important behavior: When **Token tool** is ON, the DM fog brush is intentionally disabled (including brush preview) to prevent accidental fog edits.
- Click **Import Token** to load a `.png` / `.jpg` token image.
- Enable **Token tool** to manipulate tokens on the DM canvas:
  - Drag token body: move
  - Blue handle icon (top-right): resize
  - Orange handle icon (above token): rotate
- Right-click a selected token to open the context menu (Rotate, Resize, Copy, Paste, Delete)
- **Duplicate** / **Bring to Front** / **Send to Back**
- Press **Delete** or **Backspace** to remove the selected token.

______________________________

Rapid Map
Cŕée un nouveau bouton nommé "Rapid Map" situé à droite du bouton "Storyboard" dans le bandeau supérieur de l'application.
Lorsqu'on clique sur ce bouton, il y a une colonne qui apparait sur la partie droite de l'UI, avec le même design que la colonne se trouvant à gauche de l'interface utilisateur. Cette colonne va comporter plusieurs d'outils pour dessiner une carte.
Tant qu'on ne re-clique pas sur le bouton "Rapid Map" il reste activé et a une couleur rouge, (comme pour le bouton "Token tool").
Propose-moi des outils graphiques pour dessiner rapidement une carte.

Les outils vont chercher des images au format jpg ou png qui sont stokées dans des répertoires spécifiques de l'application. Si on ajoute des images dans ces répertoires, cela sera visible dans la liste proposée par les outils.
À chaque fois qu'on importe une image, on peut la redimensionner avec 1 seul clic, et figer sa taille avec un double clic.
- Base : liste déroulante pour faire le fond de la map (propose des fonds de cartes de différents couleurs et textures : fond d'herbe verte, fond de terre brune, fond de ville en pavés, sous-sol en roche). Il y a aussi, à côté, une liste pour choisir entre 3 tailles de la map (24", 32", 40")
- Environnement : figuré d'arbre, herbe, tracer un chemin ou une route, tracer un cours d'eau, figuré de pont, falaise, rocher, entrée de grotte.
- Urbain : figuré de route pavée, mur en pierre, en bois, porte en bois, escalier, toit de maison en vieilles tuiles 
-Sous-sol : les tracés correspondent à des zones blanches : tracer un couloir, tracer une caverne.

Les boutons "Save" et "Save as" de l'UI sont actifs pour sauvegarder le travail.
Si ouvre une map faite avec "Rapid Map Design", on peut continuer à la modifier avec "Rapid Map Design".
___________________________________


___________________________________

https://fr.pinterest.com/pin/833728949737244083/
https://fr.pinterest.com/pin/7248049391257530/
https://fr.pinterest.com/pin/3166662232523477/
https://www.patreon.com/venatusmaps/posts/urban-assets-21283469
https://www.patreon.com/venatusmaps/posts/snowy-assets-16380982

textures seamless style “Lost Trails / battlemap peint”


{"prompt":"Create a complete top-down fantasy RPG cartography asset pack in a hand-painted semi-realistic style very close to Lost Trails battlemap art. The output must contain separate assets arranged on transparent or neutral backgrounds for later slicing: 6 seamless 1024x1024 textures (lush grass, dry grass, dirt, rocky path, cliff rock, sand), 12 individual trees with soft shadows, 8 individual rocks and cliff pieces, 4 alpha path brushes, and 1 assembled example map. Consistent painterly brushwork, soft ambient lighting, rich greens and earth tones, non-photorealistic, suitable for a map editor. No text, no watermark, no UI, no labels.","size":"1792x1024","n":1,"transparent_background":false}


les dessins utilisés pour "Rapid Map" ont été générés avec Chatgpt par Cedric Dagobert
créé une illustration top-down représentant un fond d'herbe pour une battlemap de jdr. L'image généré doit avoir la taille d'un écran 24 pouces

génère une image seamless pour représenter un chemin qui pourra être utilisée avec les images que tu as généré dans un logiciel de cartographie. Cette image doit avec un fond transparent pour que les bord du chemin puissent se fondre sans problème avec les fonds de cartes que tu as généré







Hi,
You will find here my contributions on Veilforge : version 2.7.5.

## Interface 
- Updated interface version with an audacious **Tactical Studio** UI direction.

## Video / Audio maps
- You can open video or audio files directly as the map source.
- Video/audio support : open `.mp4`, `.webm`, `.mkv`, `.m4a` files for playback on the DM canvas and player screen
- When a video file is loaded, playback starts automatically and loops on the DM canvas and player screen.
- Grid on video is supported: if Grid is enabled, the overlay is drawn on video for both **DM** and **Player** views.
- Keeps all heavy-video protections introduced previously (heavy detection, lite profile, VP9 4K safeguard, 1080p cache transcode attempt).

### Video playback limitations and stability notes
- Very heavy videos (especially 4K and/or high bitrate files) can overload some systems and cause UI stalls.
- If this happens, Windows may briefly show "Not responding" while decoding catches up.

Veilforge mitigation behavior:
- Detects likely heavy files and shows an informational warning (size + 4K hints, and codec/resolution metadata when available).
- Automatically enables a **lite playback profile** (reduced frame processing and stronger downscale).
- VP9 4K streams force lite profile automatically.
- If ffmpeg is available on the machine, Veilforge attempts to build and reuse a local 1080p cache copy for every detected heavy video.
- Practical recommendation: For best reliability on modest hardware, prefer 1080p sources or pre-encoded lighter versions of very large maps.

## DM zoom navigation (Master screen)
- When zoom level is above 100% and movement is possible, Veilforge shows:
  - a horizontal scrollbar at the bottom
  - a vertical scrollbar on the right
- Those bars let the DM move quickly through the zoomed map area.

## Tokens
Tokens are image markers placed on top of the map (creatures, NPCs, props, effects).
- Click "Import Token" to load one or multiple `.png` / `.jpg` token images.
- Imported tokens are auto-arranged around map center with spacing (not stacked).
- Token size is normalized on import for visibility, and can be adjusted with Parameters > Token import scale.
- Multi-import spacing can be adjusted with Parameters > Token batch spacing.
- Enable "Token tool" to manipulate tokens on the DM canvas:
  - Drag token body: move
  - Blue handle icon (top-right): resize
  - Orange handle icon (above token): rotate
- Right-click a selected token to open the context menu:
  - **Undo** / **Redo**
  - **Rotate** / **Resize**
  - **Copy** / **Paste** / **Delete**
  - multi-selection enabled
- Keyboard shortcuts for tokens:
  - **Ctrl + Z**: undo token action
  - **Ctrl + Y**: redo token action
  - **Ctrl + C**: copy selected token
  - **Ctrl + V**: paste copied token
- **Delete** or **Backspace**: remove selected token
- Tokens are synchronized to the **Player** window.
- On the Player side, tokens stay hidden under fogged areas (fog is drawn above tokens).

Important behavior: When "Token tool" is ON, the DM fog brush is intentionally disabled (including brush preview) to prevent accidental fog edits.

- **Save / Save As** stores your current state of tokens (image, position, size, rotation)

## File search
- In file search dialogs, `.json` session files are explicitly listed in the main filter so they are visible without switching filters.

## Parameters
- **Parameters** includes a configurable default folder for **Save/Load Session**.
- **Parameters** includes **Token batch spacing** for multi-token import placement.

## Credits
- Cedric Dagobert — AI co-dev (versions 2.7.5)

