# What's new in CPNpy

Newest first. When a new version is out, CPNpy shows its section here (and
those of any other versions you skipped) before offering to install it, and
each [release on GitHub](https://github.com/s4mstruthers/CPNpy/releases) uses
it as its description. Write for the people using the app: what they will
notice, not how it was done.

## 0.3.10

- **Fixed:** in the net editor, dragging the gap between the canvas and the
  inspector did nothing unless the window was very wide, and on a laptop
  screen the inspector ran off the right edge behind a scroll bar. The
  editor's tool buttons now wrap onto a second line when space is short, so
  the page fits and the divider can be dragged.
- **Hide the sidebar** with the new button at the top left of every page
  (or View ▸ Show Sidebar, ⌘⌥S) to give the net the whole window. CPNpy
  remembers your choice.
- The arrow for drawing arcs now belongs to the node nearest the mouse; when
  zoomed out it could pick a neighbouring one.

## 0.3.9

- **Fixed:** adding a place or transition to a net saved in an earlier
  session could give it the same hidden id as an existing one, and then the
  net could not be saved ("An arc must connect a place and a transition").
  New places, transitions and arcs now always get an id of their own.

## 0.3.8

- **Draw nets faster.** Drag the arrow beside a place out onto empty canvas
  and let go: a new transition appears there, already joined by an arc (and
  a place, if you start from a transition). A see-through preview shows
  where it will go, and it lines up with the node you started from. Type
  its name and carry on from its own arrow. One undo takes both away.
- The arrow for drawing arcs is a little easier to see, and no longer gets
  in the way of dragging a name that sits outside its node.
- Adding a place or transition no longer shifts a small net across the
  window.

## 0.3.7

- **Snap All to Grid** replaces the *Tidy* menu: one button that moves every
  place, transition and arc bend to the nearest dot, keeping your layout.
  *Arrange Automatically* is gone: on models drawn by hand it made a worse
  layout than the one you had.
- **Fixed (mostly on Linux):** after an open file was deleted, a new file
  created in the folder could be mistaken for it having moved there -- and
  then saved over. A file now only counts as moved if it really is the same
  file.

## 0.3.6

- **Neat nets.** Tick *Snap to grid* in the editors to put new and moved
  places, transitions and arc bends on the canvas's dots. *Tidy ▸ Snap
  Everything to the Grid* neatens a net you drew freely, and *Tidy ▸ Arrange
  Automatically* lays it out afresh, left to right. Undo puts it back.
- **The arrow for drawing arcs stays out of the way.** It only appears when
  the mouse is just outside a place or transition (not over it), and it is
  fainter until you aim at it.

## 0.3.5

- **Files moved in Finder stay open.** Moving or renaming an open file inside
  the folder used to mark it as missing and list it a second time in its new
  place; now it simply follows the file.
- **Recent folders on the welcome page open again** when you click them.
- **CSV files saved by Excel on Windows** (with letters like é or ü) open
  instead of failing.
- If a net **cannot be saved automatically** (a read-only folder, a full
  disk), a bar says so once, instead of an error message after every edit.
- A log still loading when you switch to another folder no longer turns up
  in the new one.
- Check boxes, radio buttons and sliders are easier to see in dark mode.
- The `cpnpy` command line says plainly when a file is missing or cannot be
  read, instead of printing a Python error.

## 0.3.4

- **Smoother updates.** While an update is being prepared, its progress
  window now stays put and says "Preparing…" instead of flickering on and
  off. (Updating *to* this version may still flicker once: the fix is in the
  version doing the updating.)

## 0.3.3

- **A more modern look throughout.** Drop-down lists, check boxes, radio
  buttons, tooltips, the Filter dialog's sections and the other dialogs now
  have the same rounded style as the rest of the app. Drop-down lists are
  wide enough to show their longest entry in full.
- **Keyboard hints match your computer**: Windows and Linux show Ctrl and
  Backspace where a Mac shows ⌘ and ⌫.
- The dotted chart can be panned by dragging with the middle mouse button.

## 0.3.2

- **Update notices work.** In 0.3.0 and 0.3.1, checking for updates failed
  with a certificate error, so please download this version yourself once.
  From now on CPNpy tells you when a new version is out and can install it
  for you.
- **CPNpy checks for a new version every time it opens.** If there is one, a
  bar at the top of the window says so without interrupting you: *What's
  New* shows what changed in each version you don't have yet, *Install Now*
  installs it, *Skip This Version* stays quiet until the one after, and ✕
  closes the bar until next time. Turn the check off in *Settings*.

## 0.3.1

- **By kind** in the sidebar lists your files again (it showed only the
  headings).
- Pop-up menus have rounded corners, like the rest of the app.

## 0.3.0

- **Your folder and the app stay in sync.** New nets and logs are saved into
  the open folder straight away, edits are saved as you go, and files you add,
  change or delete in Finder show up in the app by themselves.
- **Subfolders in the sidebar**, with a *Folders* / *By kind* switch. Make,
  rename and move folders and files, or move them to the Bin, from the
  sidebar.
- **Opening a file from elsewhere** offers to copy or move it into the folder.
- **Middle-click and drag** pans the canvas reliably.
- **Help ▸ Check for Updates…** (it only works from 0.3.2 on).
- "Workspace" is now simply called a **folder**.

## 0.2.0

- **Work in a folder** such as *Week 2*: every log and net in it is listed in
  the sidebar, and what you had open comes back next time.
- *Save As* names a net after its file, and double-clicking a name renames
  it (and its file).

## 0.1.0

- The first standalone apps for macOS, Windows and Linux: no Python needed.
