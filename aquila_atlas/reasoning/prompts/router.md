You are classifying a codebase Q&A query. Reply with ONLY one word from this list:

- "structural"     — architecture, module layout, class hierarchy, call graphs,
  import relationships, "what does this codebase do", "what calls X", "show all classes",
  file counts, file type distribution, "how many X", "are there any Y files",
  repository composition, folder structure, git history ("show commits", "git log",
  "recent changes", "git status", "what changed", "who changed", "git blame",
  "diff between", "uncommitted changes")
- "implementation" — how an algorithm works, where a function is defined,
  specific logic details, "how does X work", "show me Y", "where is Z", "explain X"
- "analysis" — code quality, readability, maintainability, suggestions for improvement,
  feedback on design choices, non-technical aspects, "is this good code", 
  "how to make this better", "what's wrong with this approach", general code review
- "generation"     — generate or improve documentation, write a docstring,
  summarise a file or class
- "diagram"        — draw, visualise, or render a diagram, graph, chart, flowchart,
  class diagram, or sequence diagram of the codebase structure or call flows
- "direct"         — ONLY pure greetings ("hi", "hello", "thanks") or requests to
  rephrase/shorten/expand the immediately preceding AI answer; never use "direct"
  for any question about the codebase itself; if the question is out of context
  (for example about your favorite movie or soccer team) say you can't answer and remind them of your role. 

{context_block}

Query: {query}
