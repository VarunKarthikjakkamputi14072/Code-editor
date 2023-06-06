IMPLEMENTATION OF FRONTEND :
The frontend of the project is implemented using the tkinter library in Python.
The code for the frontend is as follows:
root = tk.Tk() root.title("Lexical
Analyzer")
# create a menu bar
menubar = tk.Menu(root)
filemenu = tk.Menu(menubar, tearoff=0)
filemenu.add_separator()
filemenu.add_command(label="Exit", command=root.quit)
menubar.add_cascade(label="File", menu=filemenu)
# create a text area textarea = tk.Text(root)
textarea.pack(fill=tk.BOTH, expand=True) # create a
button to implement the lexical analyzer b1 =
tk.Button(root, text="Get tokens", command=lambda:
lexical_analyzer(textarea.get("1.0", tk.END)))
# set padding for the button b1.pack(pady=30,
padx=30) b1.pack(side=tk.BOTTOM)
# create a button to implement the syntax analyzer b2
= tk.Button(root, text="Check for Errors",
command=lambda:
render_syntax_check_result(syntax_check(textarea.get("1.0", tk.END))))
# set padding for the button
b2.pack(pady=30, padx=30)
b2.pack(side=tk.BOTTOM)
# configure the window
root.config(menu=menubar)
# set the window size to full screen
root.state("zoomed")
root.mainloop()
