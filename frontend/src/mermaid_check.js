import mermaid from "mermaid";

const input = process.argv[2];

function safeParse(diagram) {
    try {
        // IMPORTANT: disable DOM rendering dependencies
        mermaid.initialize({
            startOnLoad: false,
            securityLevel: "strict"
        });

        mermaid.parse(diagram);
        return { valid: true };
    } catch (err) {
        return {
            valid: false,
            error: err?.str || err?.message || String(err)
        };
    }
}

const result = safeParse(input);
console.log(JSON.stringify(result));