As researchers and PhD students, we all know this folder:
```
1-s2.0-S0001457525001344-main.pdf
nihms-1234567.pdf
2403.01234v2.pdf
download (3).pdf
```
Every paper we download arrives with a name that means nothing, so we rename them by hand, one by one. Year, author, title. Again and again.

What if your computer just took care of it?

So I built PaperNym (pronounced PAY-per-nim), a free and open-source tool that watches your folders and renames every paper PDF the moment it lands:
```
1-s2.0-S0001457525001344-main.pdf
→ 2025_Islam_Evaluating_crash_risk_factors_of_farm_equipment_vehicles….pdf
```
How it works:
🔎 It finds the paper's DOI or arXiv ID and looks it up in Crossref, OpenAlex, Semantic Scholar and arXiv
✅ It checks that the record really matches the PDF before renaming. A file is left alone rather than given a wrong name.
📝 15 name formats (year–author–title, citekeys, Zotero style), or your own template, with a live preview
↩️ Every rename can be undone, and a name you set by hand is never changed
📶 Works offline: papers get a temporary _CHECK name and are fixed automatically once you are back online
🔒 Private: no account, no tracking, and your PDFs never leave your computer
🖥️ A tray app that works quietly in the background, plus a command line for scripting

Get it:
• Windows installer: https://github.com/Xatta-Trone/papernym/releases/latest
• Python (3.10+): pip install papernym
• Source and docs: https://github.com/Xatta-Trone/papernym

It's MIT-licensed and still early. If you try it, I'd love to hear which name format you use and anything it gets wrong. Issues and ideas are welcome on GitHub.

#PhDLife #Academia #Research #OpenSource #Python #ResearchTools #ReferenceManagement #GradSchool
