"""Script to list all the modules and packages used by a Brython page

It parses the HTML page, detecting the tags <script type="text/python"> and
gets the Python code embedded inside these tags, or of the external Python
scripts if the tag has an attribute "src".

Use module ast to detect all the imports in the scripts, either "import X"
or "from A import B". Then try to find the modules or packages referenced by
these imports ; for those that are found, again detect all imports 
recursively.

"""

import os
import io
import re
import tokenize
import token
import ast
import html.parser

www = os.path.join(os.path.dirname(os.getcwd()), 'www')

js_path = os.path.join(www, 'src', 'libs')

paths = [os.path.join(www, 'src', 'Lib'),
    js_path,
    os.path.join(www, 'src', 'Lib/site-packages')]

class ImportLister(ast.NodeVisitor):

    """Store all imports in a dictionary indexed by module or
    package name
    imports[name] = None for "import name"
    imports[name] = package for "from X import name"
    """
    def __init__(self):
        ast.NodeVisitor()
        self.imports = {}

    def visit_Import(self, node):
        for imported in node.names:
            self.imports[imported.name] = None
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for name in node.names:
            self.imports[name.name] = node.module
        self.generic_visit(node)


class ScriptsFinder(html.parser.HTMLParser):

    def __init__(self, script_path):
        html.parser.HTMLParser.__init__(self)
        self.scripts = {}
        self.python = False
        self.counter = None
        
        self.script_path = script_path
        self.folder = os.path.dirname(script_path)
        
        self.imported = {}
        self.not_found = set()
        
        with open(self.script_path, encoding='utf-8') as fobj:
            src = fobj.read()
            self.feed(src)

            for script, [script_path, src] in self.scripts.items():
                self.find_modules(script_path, src)
        
    def handle_starttag(self, tag, attrs):
        """Set self.python to True if tag is script and
        type = text/python and src is not set
        """
        
        if tag=='script':
            src = None
            python = False
            _id = None

            for key, value in attrs:
                if key=='type' and value.lower() in ['text/python',
                    'text/python3']:
                    python = True
                elif key=='src':
                    src = value
                elif key == 'id':
                    _id = value

            if python:
                # get script id
                if _id is not None:
                    self._id = _id
                elif self.counter is None:
                    self._id = '__main__'
                    self.counter = 1
                else:
                    self._id = '__main__{}'.format(self.counter)
                    self.counter += 1

                if not src:
                    # set attribute python to store next HTML data
                    self.python = True
                else:
                    # find url of external script
                    path = os.path.join(self.folder, *src.split('/'))
                    with open(path, 'rb') as ext_script_obj:
                        self.scripts[self._id] = [path, ext_script_obj.read()]
    
    def handle_data(self, data):
        if self.python:
            self.scripts[self._id] = [self.script_path, data.encode('utf-8')]
        self.python = False


    def find_modules(self, path, src):
        """Parse source code, store all imports"""
        imports = ImportLister()
        imports.visit(ast.parse(src))
        for name, _from in imports.imports.items():
            if _from is None:
                self.resolve_import(path, name)
            else:
                self.resolve_import_from(path, name, _from)

    def resolve_import(self, script_path, name):
        """Find module source based on script path and name
        """
        if name in self.imported or name in self.not_found:
            return
        print('resolve', name)
        elts = name.split('.')
        for mod_path in [paths[0], js_path, script_path, paths[1]]:
            if mod_path is js_path:
                module_filename = os.path.join(js_path, name+'.js')
                if os.path.exists(module_filename):
                    self.imported[name] = 'module', module_filename
                    return
                continue
            for elt in elts[:-1]:
                sub_path = os.path.join(mod_path, elt)
                if os.path.exists(os.path.join(sub_path, '__init__.py')):
                    mod_path = sub_path
                else:
                    break
            else:
                # If we get here, mod_path is the path where the module might 
                # be. 
                # Try module_name.py
                module_filename = os.path.join(mod_path, elts[-1]+'.py')
                if os.path.exists(module_filename):
                    self.imported[name] = 'module', module_filename
                    with open(module_filename, 'rb') as fobj:
                        self.find_modules(mod_path, fobj.read())
                    return module_filename
                else:
                    # try module/__init__.py
                    package_folder = os.path.join(mod_path, elts[-1])
                    package_filename = os.path.join(package_folder, 
                        '__init__.py')
                    if os.path.exists(package_filename):
                        self.imported[name] = 'package', package_filename
                        with open(package_filename, 'rb') as fobj:
                            self.find_modules(package_folder, fobj.read())
                        return package_filename
        self.not_found.add(name)
    
    def resolve_import_from(self, script_path, name, _from):
        """Resolve an import of the form "from X import name"
        found in the script at specified path
        """
        origin = self.resolve_import(script_path, _from)
        try:
            typ, filename = self.imported[_from]
        except KeyError:
            self.not_found.add(_from)
            return
    
        if typ == "package":
            # form "from package import name"
            # search a module name.py in package directory
            package_path = os.path.dirname(filename)
            module_filename = os.path.join(package_path, name+'.py')
            package_filename = os.path.join(package_path, name, '__init__.py')
            if os.path.exists(module_filename):
                self.imported[name] = 'module', module_filename
                with open(module_filename, encoding="utf-8") as fobj:
                    self.find_modules(package_path, fobj.read())
                return module_filename
            elif os.path.exists(package_filename):
                self.imported[name] = 'package', package_filename
                with open(package_filename, encoding="utf-8") as fobj:
                    self.find_modules(os.path.join(package_path, name), 
                        fobj.read())
                return package_filename
            else:
                # ignore names imported from the package __init__.py file
                return
    
        else:
            # ignore names imported from a module
            return

if __name__ == '__main__':

    finder = ScriptsFinder(os.path.join(www, 'gallery', 'clock.html'))
    
    items = sorted(finder.imported.items())
    for key, value in items:
        print(key, value)
    
    print()
    
    print('Not found\n', finder.not_found)
