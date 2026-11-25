// How much of a file is read or highlighted at a time.

export const TEXT_CHUNK = 1 << 20; // bytes of a text file shown per step

export const CSV_CHUNK = 8 << 20; // bytes of a table parsed per step

export const HIGHLIGHT_MAX = 256 << 10;

export const AUTO_RELOAD_MAX = 2 << 20;

export const JUMP_MAX = 64 << 20; // how far a jump-to-line will read into a file
