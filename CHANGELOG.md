# What's new in CPNpy

Newest first. When a new version is out, CPNpy shows its section here (and
those of any other versions you skipped) before offering to install it, and
each [release on GitHub](https://github.com/s4mstruthers/CPNpy/releases) uses
it as its description. Write for the people using the app: what they will
notice, not how it was done.

## 0.5.2

- **Notes everywhere.** ✎ *Notes* in the bottom-left corner opens scratch
  paper over whatever you are working on: a log, a net, the welcome page.
  Drag its header to move it out of the way and its corner to resize it;
  ⤢ makes it larger, and – folds it back into the button. *View ▸ Show
  Notes* (⌘⌥N) opens and closes it, and *View ▸ Show Notes Button* hides the
  button if you would rather just use the shortcut.
- **Each folder keeps its own notes**, so they travel with the folder (iCloud,
  Git). Outside a folder you have one set of notes, kept by the app.

## 0.5.1

- **Notes in exercises.** ✎ *Notes* in the top bar opens scratch paper under
  the worksheet, for working things out before you answer. It is kept with
  the exercise (*my notes.md*).
- **Older exercises are easier to answer.** A sheet written before answer
  boxes, in parts a., b., c., now has a box under each part, with that part
  of the worked answer behind *Show answer*.
- **The window's title names the exercise** you are working on.
- **Pictures in worksheets** wider than the sheet are scaled to fit.
- **Writing Exercise Packs** (Help menu) now walks through making a pack step
  by step, which box suits which kind of question, and turning a past exam
  into a pack.
- **Fixed:** in an answer block, `a # b` (the α-algorithm's choice relation)
  was taken for a comment and cut off. A comment now needs two spaces before
  the `#`.
- **Computed answers** `free-choice` and `dead transitions` also work for a
  net that is not a WF-net.
- **The demo exercises go where you say.** *Open Demo Exercises* asks where
  to put its copy (nothing is copied until you choose), remembers it, and no
  longer switches the folder you are working in.

## 0.5.0

- **Exercise mode.** Exercises now open in a view of their own, made for
  working through them: the worksheet on the left with an answer box
  wherever one is needed, and what the exercise gives (the log, the
  transition system, the net, your net) on the right. Answer as you would on
  paper — yes/no, choices, sets like `{a, b}` or `({a}, {b,d})`, a footprint
  matrix to fill in, a firing sequence, a number, a net — and press
  **Check**: most answers are checked straight away, and when one is not
  right you see how far off it is without being given the answer. *Hint*
  and *Show answer* when you want them. Your answers are saved in the
  exercise's folder as you go, and the top bar shows your progress and steps
  through the pack.
- **Writing exercise packs** is plain Markdown: an `answer` block wherever
  students should answer. Right answers can be worked out by the app from the
  exercise's log, net or transition system (`compute: alpha.Y_L`,
  `compute: sound`, `compute: pre-regions(c)`, …). *Help ▸ Writing Exercise
  Packs* has the details, and `cpnpy exercises check` finds mistakes in a
  pack before you share it. The demo exercises are rewritten this way.
- **Edit a log** after opening it (*Edit…* on its page): as notation — a log
  you typed comes back exactly as you typed it — or case by case: events,
  timestamps, resources, cases, and renaming or removing an activity
  everywhere. Changes are saved to the log's file. A log typed in notation is
  now kept as a `.log.txt` file, in notation.
- **The canvas goes on in every direction.** Scrolling (two fingers on a
  trackpad) pans whether or not the whole net is in view, so you can always
  make room to start a new part beside it. Hold Space and drag to pan with
  the mouse. Zooming with ⌘-scroll or a pinch keeps the point under the
  pointer where it is.
  Pan the net right out of view and a button at the top of the canvas
  points to where it went; click it to bring it back.
- **Help ▸ References** lists the books, papers and standards behind every
  notation and algorithm in CPNpy (also in `docs/references.md`).

## 0.4.1

- **The sidebar button is on the sidebar.** Hide it with the button at its
  top right; while it is hidden, a slim strip at the left edge of the window
  has the button that brings it back.
- **Exercises are tidier on a laptop.** Check and Reveal all sit at the foot
  of the question. The question folds away with ‹ (and comes back from the
  left edge). In a narrow window, opening an exercise folds the sidebar away
  until you close the exercise. *my answer* is listed inside its exercise.
- **Fixed:** with an exercise open the net editor could again need more room
  than the window had, so the page scrolled sideways and the divider beside
  the canvas would not move. When space is short the inspector now folds
  away by itself (*⇤ Inspector* brings it back) and returns when there is
  room.

## 0.4.0

- **Exercises.** A folder with a `question.md` (or `.pdf` / `.png`) is now an
  exercise: click it in the sidebar and the question appears beside the
  canvas, the given net or log is loaded, and the analysis results stay
  hidden until you reveal them, one at a time or with *Reveal all*. Your
  work is saved as `my answer.pnml`, so a given `net.pnml` is never changed.
  **Check** compares your net with the model answer (`answer.pnml`) on what
  it can do, not how it is drawn, and shows the shortest traces where they
  differ, each of which you can replay in the token game. Without a model
  answer, Check shows the worked answer (`answer.md`).
- **Demo exercises**: File ▸ Open Demo Exercises copies a few to
  *Documents/CPNpy Exercises* to try.
- **State-based regions** in Discover: the log becomes a transition system
  (choose the prefix or postfix, set, multiset or sequence, and how many
  events to look back), and its minimal regions become the places of a
  net. The derivation shows every step the way exam answers are written:
  the transition system, GER and minimal pre-regions of every event, state
  separation, forward closure, and whether the net behaves exactly like the
  transition system.
- **Transition systems** of your own: File ▸ New Transition System…, or a
  `ts.txt` file. *Is this a region?* checks any set of states, and says
  which event breaks it when it is not one.
- **Compare nets…** (File menu and sidebar): do two nets allow the same
  traces? With the shortest differences both ways.
- Logs written in textbook notation open from `log.txt` (or `name.log.txt`)
  files.
- New definitions on hover and in Help ▸ Definitions: region, minimal
  region, pre- and post-region, GER, state separation, forward closure,
  elementary transition system and synthesis.

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
