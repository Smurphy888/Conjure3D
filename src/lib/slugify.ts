export function slugify(name: string, fallback = "model", maxLen = 40): string {
    let s = name.toLowerCase();
    s = s.replace(/[\s_]+/g, "-");
    s = s.replace(/[^a-z0-9-]/g, "");
    s = s.replace(/-+/g, "-").replace(/^-+|-+$/g, "");
    s = s.slice(0, maxLen).replace(/-+$/, "");
    return s || fallback;
}
