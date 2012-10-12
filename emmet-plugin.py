import sublime
import sublime_plugin

import re
import json
import os.path
import traceback

import completions as cmpl
from completions.meta import HTML_ELEMENTS_ATTRIBUTES, HTML_ATTRIBUTES_VALUES
from emmet.context import Context

__version__      = '1.0'
__core_version__ = '1.0'
__authors__      = ['"Sergey Chikuyonok" <serge.che@gmail.com>'
					'"Nicholas Dudfield" <ndudfield@gmail.com>']

BASE_PATH = os.path.abspath(os.path.dirname(__file__))
EMMET_GRAMMAR = os.path.join(BASE_PATH, 'Emmet.tmLanguage')

def active_view():
	return sublime.active_window().active_view()

def replace_substring(start, end, value, no_indent=False):
	view = active_view()
	# edit = view.begin_edit()

	view.sel().clear()
	view.sel().add(sublime.Region(start, end or start)) 

	# XXX a bit naive indentation control. It handles most common
	# `no_indent` usages like replacing CSS rule content, but may not
	# produce expected result in all possible situations
	if no_indent:
		line = view.substr(view.line(view.sel()[0]))
		value = unindent_text(value, get_line_padding(line))

	view.run_command('insert_snippet', {'contents': value.decode('utf-8')})
	# view.end_edit(edit)

def unindent_text(text, pad):
	"""
	Removes padding at the beginning of each text's line
	@type text: str
	@type pad: str
	"""
	lines = text.splitlines()
	
	for i,line in enumerate(lines):
		if line.startswith(pad):
			lines[i] = line[len(pad):]
	
	return '\n'.join(lines)

def get_line_padding(line):
	"""
	Returns padding of current editor's line
	@return str
	"""
	m = re.match(r'^(\s+)', line)
	return m and m.group(0) or ''

def update_settings():
	ctx.set_ext_path(settings.get('extensions_path', None))

	keys = ['snippets', 'preferences', 'syntaxProfiles', 'profiles']
	payload = {}
	for k in keys:
		data = settings.get(k, None)
		if data:
			payload[k] = data

	ctx.reset()
	ctx.load_user_data(json.dumps(payload))

# load settings
settings = sublime.load_settings('Emmet.sublime-settings')
settings.add_on_change('extensions_path', update_settings)

# provide some contributions to JS
contrib = {
	'sublime': sublime, 
	'sublimeReplaceSubstring': replace_substring
}

# create JS environment
ctx = Context(['../editor.js'], settings.get('extensions_path', None), contrib)

update_settings()

sublime.set_timeout(cmpl.remove_html_completions, 2000)

class RunEmmetAction(sublime_plugin.TextCommand):
	def run(self, edit, action=None, **kw):
		run_action(lambda i, sel: ctx.js().locals.pyRunAction(action))
		# ctx.js().locals.pyRunAction(action)

def run_action(action, view=None):
	"Runs Emmet action in multiselection mode"
	if not view:
		view = active_view()

	region_key = '__emmet__'
	sels = list(view.sel())
	r = ctx.js().locals.pyRunAction
	result = False

	edit = view.begin_edit()
	max_sel_ix = len(sels) - 1

	try:
		for i, sel in enumerate(reversed(sels)):
			view.sel().clear()
			view.sel().add(sel)
			# run action
			# result = r(name) or result
			result = action(max_sel_ix - i, sel) or result

			# remember resulting selections
			view.add_regions(region_key,
					(view.get_regions(region_key) + list(view.sel())) , '')
	except Exception, e:
		view.erase_regions(region_key)
		print(traceback.format_exc())
		return
	

	# output all saved regions as selection
	view.sel().clear()
	for sel in view.get_regions(region_key):
		view.sel().add(sel)

	view.erase_regions(region_key)

	view.end_edit(edit)

	return result

class ExpandAbbreviationByTab(sublime_plugin.TextCommand):
	def run(self, edit, **kw):
		# this is just a stub, the actual abbreviation expansion
		# is done in TabExpandHandler.on_query_context
		pass


class TabExpandHandler(sublime_plugin.EventListener):
	def correct_syntax(self, view):
		return view.match_selector( view.sel()[0].b, cmpl.EMMET_SCOPE )

	def html_elements_attributes(self, view, prefix, pos):
		tag         = cmpl.find_tag_name(view, pos)
		values      = HTML_ELEMENTS_ATTRIBUTES.get(tag, [])
		return [(v,   '%s\t@%s' % (v,v), '%s="$1"' % v) for v in values]

	def html_attributes_values(self, view, prefix, pos):
		attr        = cmpl.find_attribute_name(view, pos)
		values      = HTML_ATTRIBUTES_VALUES.get(attr, [])
		return [(v, '%s\t@=%s' % (v,v), v) for v in values]

	def completion_handler(self, view):
		"Returns completions handler fo current caret position"
		black_list = settings.get('completions_blacklist', [])

		# A mapping of scopes, sub scopes and handlers, first matching of which
		# is used.
		COMPLETIONS = (
			(cmpl.HTML_INSIDE_TAG, self.html_elements_attributes),
			(cmpl.HTML_INSIDE_TAG_ATTRIBUTE, self.html_attributes_values)
		)

		pos = view.sel()[0].b

		# Try to find some more specific contextual abbreviation
		for sub_selector, handler in COMPLETIONS:
			h_name = handler.__name__
			if h_name in black_list: continue
			if (view.match_selector(pos,  sub_selector) or
				 view.match_selector(pos - 1,  sub_selector)):
				return handler

		return None

	def on_query_context(self, view, key, op, operand, match_all):
		if key != 'is_abbreviation':
			return False

		# print(view.syntax_name(view.sel()[0].begin()))

		# we need to filter out attribute completions if 
		# 'disable_completions' option is not active
		if (not settings.get('disable_completions', False) and 
			self.correct_syntax(view) and 
			self.completion_handler(view)):
			return False

		# let's see if Tab key expander should be disabled for current scope
		banned_scopes = settings.get('disable_tab_abbreviations_for_scopes', '')
		if banned_scopes and view.match_selector(view.sel()[0].b, banned_scopes):
			return False

		return run_action(lambda i, sel: ctx.js().locals.pyRunAction('expand_abbreviation'))
		# return ctx.js().locals.pyRunAction('expand_abbreviation')

	def on_query_completions(self, view, prefix, locations):
		if ( not self.correct_syntax(view) or
			 settings.get('disable_completions', False) ): return []

		handler = self.completion_handler(view)
		if handler:
			pos = view.sel()[0].b
			completions = handler(view, prefix, pos)
			return completions

		return []
		

class CommandsAsYouTypeBase(sublime_plugin.TextCommand):
	history = {}
	filter_input = lambda s, i: i
	selection = ''
	grammar = EMMET_GRAMMAR

	def setup(self):
		pass

	def run_command(self, view, value):
		if '\n' in value:
			for sel in view.sel():
				trailing = sublime.Region(sel.end(), view.line(sel).end())
				if view.substr(trailing).isspace():
					view.erase(self.edit, trailing)

		view.run_command('insert_snippet', { 'contents': value.decode('utf-8') })

	def insert(self, abbr):
		view = self.view

		if not abbr and self.erase:
			self.undo()
			self.erase = False
			return

		def inner_insert():
			self._real_insert(abbr)

		self.undo()
		sublime.set_timeout(inner_insert, 0)

	def _real_insert(self, abbr):
		view = self.view
		self.edit = edit = view.begin_edit()
		cmd_input = self.filter_input(abbr) or ''
		try:
			self.erase = self.run_command(view, cmd_input) is not False
		except:
			pass
		view.end_edit(edit)

	def undo(self):
		if self.erase:
			sublime.set_timeout(lambda: self.view.run_command('undo'), 0)

	def remember_sels(self, view):
		self._sels = list(view.sel())
		self._sel_items = []

		for sel in self._sels:
			# selection should be unindented in order to get desired result
			line = view.substr(view.line(sel))
			s = view.substr(sel)
			self._sel_items.append(unindent_text(s, get_line_padding(line)))

	def run(self, edit, **args):
		self.setup()
		self.erase = False

		panel = self.view.window().show_input_panel (
			self.input_message, self.default_input, None, self.insert, self.undo )

		panel.sel().clear()
		panel.sel().add(sublime.Region(0, panel.size()))

		if self.grammar:
			panel.set_syntax_file(self.grammar)
			setting = panel.settings().set

			setting('line_numbers',   False)
			setting('gutter',         False)
			setting('auto_complete',  False)
			setting('tab_completion', False)
			# setting('auto_id_class',  True)

class WrapAsYouType(CommandsAsYouTypeBase):
	default_input = 'div'
	input_message = "Enter Wrap Abbreviation: "

	def setup(self):
		view = active_view()
		
		if len(view.sel()) == 1:
			# capture wrapping context (parent HTML element) 
			# if there is only one selection
			r = ctx.js().locals.pyCaptureWrappingRange()
			if not r:
				return # nothing to wrap

			view.sel().clear()
			view.sel().add(sublime.Region(r[0], r[1]))
			view.show(view.sel())

		self.remember_sels(view)

	# override method to correctly wrap abbreviations
	def _real_insert(self, abbr):
		view = self.view
		self.edit = edit = view.begin_edit()
		self.erase = True

		# restore selections
		view.sel().clear()
		for sel in self._sels:
			view.sel().add(sel)

		def ins(i, sel):
			try:
				output = ctx.js().locals.pyWrapAsYouType(abbr, self._sel_items[i])
				self.run_command(view, output)
			except Exception:
				"dont litter the console"

		run_action(ins, view)
		view.end_edit(edit)

class ExpandAsYouType(WrapAsYouType):
	default_input = 'div'
	input_message = "Enter Abbreviation: "

	def setup(self):
		self.remember_sels(active_view())


class HandleEnterKey(sublime_plugin.TextCommand):
	def run(self, edit, **kw):
		view = active_view()
		if settings.get('clear_fields_on_enter_key', False):
			view.run_command('clear_fields')

		# let's see if we have to insert formatted linebreak
		scope = view.syntax_name(view.sel()[0].begin())
		if sublime.score_selector(scope, settings.get('formatted_linebreak_scopes', '')) > 0:
			view.run_command('insert_snippet', {'contents': '\n\t${0}\n'})
		else:
			view.run_command('insert_snippet', {'contents': '\n${0}'})

class RenameTag(sublime_plugin.TextCommand):
	def run(self, edit, **kw):
		ranges = ctx.js().locals.pyGetTagNameRanges()
		if ranges:
			view = active_view()
			view.sel().clear()
			for r in ranges:
				view.sel().add(sublime.Region(r[0], r[1]))
			view.show(view.sel())

class EmmetInsertAttribute(sublime_plugin.TextCommand):
	def run(self, edit, attribute=None, **kw):
		if not attribute:
			return

		view = active_view()
		prefix = ''
		if view.sel():
			sel = view.sel()[0]
			if not view.substr(sublime.Region(sel.begin() - 1, sel.begin())).isspace():
				prefix = ' '

		view.run_command('insert_snippet', {'contents': '%s%s="$1"' % (prefix, attribute)})


