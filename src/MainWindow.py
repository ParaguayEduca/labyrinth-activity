# MainWindow.py
# This file is part of Labyrinth
#
# Copyright (C) 2006 - Don Scorgie <Don@Scorgie.org>
#
# Labyrinth is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Labyrinth is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Labyrinth; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA  02110-1301  USA
#

import gtk
import cairo, pangocairo
import sha
import os
import tarfile
import gobject
import gettext
_ = gettext.gettext
import MMapArea
import UndoManager
import utils
from MapList import MapList
import xml.dom.minidom as dom
import PeriodicSaveThread
import ImageThought
import TextThought

# UNDO varieties for us
UNDO_MODE = 0
UNDO_SHOW_EXTENDED = 1

class LabyrinthWindow (gtk.Window):
	__gsignals__ = dict (title_changed		= (gobject.SIGNAL_RUN_FIRST,
											   gobject.TYPE_NONE,
											   (gobject.TYPE_STRING, gobject.TYPE_OBJECT)),
						 doc_save			= (gobject.SIGNAL_RUN_FIRST,
											   gobject.TYPE_NONE,
											   (gobject.TYPE_STRING, gobject.TYPE_OBJECT)),
						 file_saved         = (gobject.SIGNAL_RUN_FIRST,
						 					   gobject.TYPE_NONE,
						 					   (gobject.TYPE_STRING, gobject.TYPE_OBJECT)),
						 window_closed      = (gobject.SIGNAL_RUN_FIRST,
						 					   gobject.TYPE_NONE,
						 					   (gobject.TYPE_OBJECT, )))

	def __init__ (self, filename, imported=False):
		super(LabyrinthWindow, self).__init__()
		if os.name != 'nt':
			try:
				self.set_icon_name ('labyrinth')
			except:
				self.set_icon_from_file(utils.get_data_file_name('labyrinth.svg'))
		else:
			self.set_icon_from_file('images\\labyrinth-24.png')

		if gtk.gtk_version[1] > 8:
		# FIXME:  This can go when we move entirely to gtk 2.10
		# pygtk 2.8 doesn't have the correct function :(
			self.set_val = True
		else:
			self.set_val = False

		# First, construct the MainArea and connect it all up
		self.undo = UndoManager.UndoManager (self)
		self.undo.block ()
		self.MainArea = MMapArea.MMapArea (self.undo)
		self.set_focus_child (self.MainArea)
		self.MainArea.connect ("title_changed", self.title_changed_cb)
		self.MainArea.connect ("doc_save", self.doc_save_cb)
		self.MainArea.connect ("doc_delete", self.doc_del_cb)
		self.MainArea.connect ("change_mode", self.mode_request_cb)
		self.MainArea.connect ("button-press-event", self.main_area_focus_cb)
		self.MainArea.connect ("change_buffer", self.switch_buffer_cb)
		self.MainArea.connect ("thought_selection_changed", self.thought_selected_cb)
		if os.name != 'nt':
			self.MainArea.connect ("text_selection_changed", self.selection_changed_cb)
		self.MainArea.connect ("set_focus", self.main_area_focus_cb)
		self.MainArea.connect ("set_attrs", self.attrs_cb)

		# Then, construct the menubar and toolbar and hook it all up
		self.create_ui ()

		# TODO: Bold, Italics etc.
		self.bold_widget = self.ui.get_widget('/AddedTools/Bold')
		self.bold_block = False
		self.bold_state = False
		self.italic_widget = self.ui.get_widget('/AddedTools/Italics')
		self.italic_block = False
		self.italic_state = False
		self.underline_widget = self.ui.get_widget('/AddedTools/Underline')
		self.underline_block = False
		self.underline_state = False

		toolbar = self.ui.get_widget('/AddedTools')
		self.font_widget = gtk.FontButton()
		self.font_widget.set_use_font (True)
		toolitem = gtk.ToolItem()
		toolitem.add(self.font_widget)
		toolbar.insert(toolitem, -1)
		self.font_widget.connect ("font-set", self.font_change_cb)

		self.background_widget = gtk.ColorButton(gtk.gdk.color_parse("white"))
		self.background_widget.set_title(_("Choose background color"))
		toolitem = gtk.ToolItem()
		toolitem.add(self.background_widget)
		toolbar.insert(toolitem, -1)
		self.background_widget.connect ("color-set", self.background_change_cb)

		self.foreground_widget = gtk.ColorButton(gtk.gdk.color_parse("black"))
		self.foreground_widget.set_title(_("Choose foreground color"))
		toolitem = gtk.ToolItem()
		toolitem.add(self.foreground_widget)
		toolbar.insert(toolitem, -1)
		self.foreground_widget.connect ("color-set", self.foreground_change_cb)

		self.cut = self.ui.get_widget ('/MenuBar/EditMenu/Cut')
		self.copy = self.ui.get_widget ('/MenuBar/EditMenu/Copy')
		self.paste = self.ui.get_widget ('/MenuBar/EditMenu/Paste')
		self.link = self.ui.get_widget ('/MenuBar/EditMenu/LinkThoughts')
		self.delete = self.ui.get_widget ('/MenuBar/EditMenu/DeleteNodes')
		
		# get toolbars and activate corresponding menu entries
		self.main_toolbar = self.ui.get_widget ('/ToolBar')
		self.format_toolbar = self.ui.get_widget ('/AddedTools')
		self.ui.get_widget('/MenuBar/ViewMenu/ShowToolbars/ShowMainToolbar').set_active(True)
		self.ui.get_widget('/MenuBar/ViewMenu/ShowToolbars/ShowFormatToolbar').set_active(True)		

		self.ui.get_widget('/MenuBar/EditMenu').connect ('activate', self.edit_activated_cb)
		self.cut.set_sensitive (False)
		self.copy.set_sensitive (False)

		# Add in the extended info view
		self.extended = gtk.TextView ()
		self.extended.set_wrap_mode (gtk.WRAP_WORD_CHAR)
		self.invisible_buffer = gtk.TextBuffer ()

		# Connect all our signals
		self.connect ("configure_event", self.configure_cb)
		self.connect ("window-state-event", self.window_state_cb)
		self.connect ("destroy", self.close_window_cb)

		# Deal with loading the map
		if not filename:
			self.MainArea.set_size_request (600, 500)
			# TODO: This shouldn't be set to a hard-coded number.  Fix.
			self.pane_pos = 500
			self.title_cp = _("Untitled Map")
			self.mode = MMapArea.MODE_EDITING
			self.extended_visible = False
		else:
			self.parse_file (filename)
			
		# Setup treeview for a11y
		self.create_tree_view()
		self.MainArea.initialize_model(self.tree_model)

		# Add all the extra widgets and pack everything in
		self.swin = gtk.ScrolledWindow ()
		self.swin.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
		self.swin.add (self.extended)

		up_box = gtk.EventBox()
		up_arrow = gtk.Arrow(gtk.ARROW_UP, gtk.SHADOW_IN)
		up_box.add(up_arrow)
		up_box.connect("button-press-event", self.translate, "Up")
		up_box.connect("button-release-event", self.finish_translate)
		down_arrow = gtk.Arrow(gtk.ARROW_DOWN, gtk.SHADOW_OUT)
		down_box = gtk.EventBox()
		down_box.add(down_arrow)
		down_box.connect("button-press-event", self.translate, "Down")
		down_box.connect("button-release-event", self.finish_translate)
		right_box = gtk.EventBox()
		right_arrow = gtk.Arrow(gtk.ARROW_RIGHT, gtk.SHADOW_OUT)
		right_box.add(right_arrow)
		right_box.connect("button-press-event", self.translate, "Right")
		right_box.connect("button-release-event", self.finish_translate)
		left_box = gtk.EventBox()
		left_arrow = gtk.Arrow(gtk.ARROW_LEFT, gtk.SHADOW_IN)
		left_box.add(left_arrow)
		left_box.connect("button-press-event", self.translate, "Left")
		left_box.connect("button-release-event", self.finish_translate)

		nvbox = gtk.VBox ()
		hbox = gtk.HBox ()
		nvbox.pack_start (up_box, False)
		hbox.pack_start (left_box, False)
		hbox.pack_start (self.MainArea)
		hbox.pack_start (right_box, False)
		nvbox.pack_start (hbox)
		nvbox.pack_start (down_box, False)

		hpanes = gtk.HPaned ()
		hpanes.pack1 (self.tree_view)
		hpanes.pack2 (nvbox)
		panes = gtk.VPaned ()
		panes.connect ("button-release-event", self.pos_changed)
		panes.add1 (hpanes)
		panes.add2 (self.swin)
		panes.set_position (self.pane_pos)

		vbox = gtk.VBox ()
		vbox.pack_start(self.ui.get_widget('/MenuBar'), expand=False)
		vbox.pack_start(self.main_toolbar, expand=False)
		vbox.pack_start (panes)
		vbox.pack_end(self.format_toolbar, expand=False)

		self.add (vbox)

		# Other stuff
		self.width, self.height = self.get_size ()
		
		# if we import, we dump the old filename to create a new hashed one
		if imported:
			self.save_file = None
		else:
			self.save_file = filename
			
		self.maximised = False
		self.view_type = 0
		#self.set_title (self.title_cp)
		if self.set_val:
			self.act.set_current_value (self.mode)
		self.ext_act.set_active (self.extended_visible)

		# Show everything required
		vbox.show ()
		self.ui.get_widget('/MenuBar').show_all ()
		self.main_toolbar.show_all ()
		self.format_toolbar.show_all ()
		hpanes.show ()
		panes.show ()
		nvbox.show ()
		up_arrow.show()
		up_box.show()
		down_arrow.show()
		down_box.show()
		hbox.show()
		left_arrow.show()
		left_box.show()
		right_arrow.show()
		right_box.show()
		self.MainArea.show ()
		self.extended.show ()
		self.tree_view.hide_all ()
		self.undo.unblock ()

		self.start_timer ()

	def create_ui (self):
		actions = [
			('FileMenu', None, _('File')),
			('Export', None, _('Export as Image'), None,
			 _("Export your map as an image"), self.export_cb),
			('ExportMap', gtk.STOCK_SAVE_AS, _('Export Map...'), '<control>S',
			 _("Export your map as XML"), self.export_map_cb),
			('Close', gtk.STOCK_CLOSE, None, '<control>W',
			 _('Close the current window'), self.close_window_cb),
			('EditMenu', None, _('_Edit')),
			('ViewMenu', None, _('_View')),
			('ShowToolbars', None, _('_Toolbar')),
			('Undo', gtk.STOCK_UNDO, None, '<control>Z', None),
			('Redo', gtk.STOCK_REDO, None, '<control><shift>Z', None),
			('Cut', gtk.STOCK_CUT, None, '<control>X',
			 None, self.cut_text_cb),
			('Copy', gtk.STOCK_COPY, None, '<control>C',
			 None, self.copy_text_cb),
			('Paste', gtk.STOCK_PASTE, None, '<control>V',
			 None, self.paste_text_cb),
			('LinkThoughts', None, _("Link Thoughts"), '<control>L',
			_("Link the selected thoughts"), self.link_thoughts_cb),
			('ModeMenu', None, _('_Mode')),
			('DeleteNodes', gtk.STOCK_DELETE, _('_Delete'), 'Delete',
			 _('Delete the selected element(s)'), self.delete_cb),
			('ZoomIn', gtk.STOCK_ZOOM_IN, None, '<control>plus',
			 None, self.zoomin_cb),
			('ZoomOut', gtk.STOCK_ZOOM_OUT, None, '<control>minus',
			 None, self.zoomout_cb)]
		self.radio_actions = [
			('Edit', gtk.STOCK_EDIT, _('_Edit Mode'), '<control>E',
			 _('Turn on edit mode'), MMapArea.MODE_EDITING),
			 ('AddImage', gtk.STOCK_ADD, _('_Add Image'), None,
			 _('Add an image to selected thought'), MMapArea.MODE_IMAGE),
			 ('Drawing', gtk.STOCK_COLOR_PICKER, _('_Drawing Mode'), None,
			 _('Make a pretty drawing'), MMapArea.MODE_DRAW)
			]
		self.view_radio_actions = [
			('UseBezier', None, _('Use _Curves'), None,
			 _('Use curves as links'), MMapArea.VIEW_BEZIER),
			 ('UseLines', None, _('Use _Lines'), None,
			 _('Use straight lines as links'), MMapArea.VIEW_LINES)]
		self.toggle_actions = [
			('ViewExtend', None, _('_Extended Information'), None,
			 _('Show extended information for thoughts'), self.view_extend_cb),
			('ViewOutline', None, _('_Outline'), None,
			 _('Show outline of thought hierarchy'), self.view_outline_cb),
			('ShowMainToolbar', None, _('_Main'), None,
			 _('Show main toolbar'), self.show_main_toolbar_cb),
			('ShowFormatToolbar', None, _('_Format'), None,
			 _('Show format toolbar'), self.show_format_toolbar_cb),
			('Bold', gtk.STOCK_BOLD, None, None,
			None, self.bold_toggled),
			('Italics', gtk.STOCK_ITALIC, None, None,
			None, self.italic_toggled),
			('Underline', gtk.STOCK_UNDERLINE, None, None,
			None, self.underline_toggled)]

		ag = gtk.ActionGroup ('WindowActions')
		ag.add_actions (actions)
		ag.add_radio_actions (self.radio_actions)
		ag.add_radio_actions (self.view_radio_actions)
		ag.add_toggle_actions (self.toggle_actions)
		self.act = ag.get_action ('Edit')
		self.ext_act = ag.get_action ('ViewExtend')
		self.act.connect ("changed", self.mode_change_cb)
		self.undo.set_widgets (ag.get_action ('Undo'), ag.get_action ('Redo'))

		self.view_action = ag.get_action('UseBezier')
		self.view_action.connect ("changed", self.view_change_cb)
		
		self.ui = gtk.UIManager ()
		self.ui.insert_action_group (ag, 0)
		self.ui.add_ui_from_file (utils.get_data_file_name('labyrinth-ui.xml'))
		self.add_accel_group (self.ui.get_accel_group ())
		
	def create_tree_view(self):
		self.tree_model = gtk.TreeStore(gobject.TYPE_STRING)
		self.tree_view = gtk.TreeView(self.tree_model)
		cell_renderer = gtk.CellRendererText()
		tree_column = gtk.TreeViewColumn(_('Thoughts'), cell_renderer)
		self.tree_view.append_column(tree_column)
		tree_column.add_attribute(cell_renderer, "text", 0)

	def link_thoughts_cb (self, arg):
		self.MainArea.link_menu_cb ()

	def undo_show_extended (self, action, mode):
		self.undo.block ()
		self.ext_act.set_active (not self.ext_act.get_active ())
		self.undo.unblock ()

	def view_extend_cb (self, arg):
		self.undo.add_undo (UndoManager.UndoAction (self, UNDO_SHOW_EXTENDED, self.undo_show_extended))
		self.extended_visible = arg.get_active ()
		if self.extended_visible:
			self.swin.show ()
			self.view_type = 1
		else:
			self.swin.hide ()
			self.view_type = 0
			
	def view_outline_cb (self, arg):
		if arg.get_active ():
			self.tree_view.show()
		else:
			self.tree_view.hide()
			
	def show_main_toolbar_cb(self, arg):
		if arg.get_active():
			self.main_toolbar.show()
		else:
			self.main_toolbar.hide()

	def show_format_toolbar_cb(self, arg):
		if arg.get_active():
			self.format_toolbar.show()
		else:
			self.format_toolbar.hide()
			
	def view_change_cb(self, base, activated):
		utils.use_bezier_curves = activated.get_current_value() == MMapArea.VIEW_BEZIER
		self.MainArea.update_all_links()
		self.MainArea.invalidate()

	def attrs_cb (self, widget, bold, italics, underline, pango_font):
		# Yes, there is a block method for signals
		# but I don't currently know how to
		# implement it for action-based signals
		# without messyness
		if bold != self.bold_state:
			self.bold_block = True
			self.bold_widget.set_active(bold)
		if italics != self.italic_state:
			self.italic_block = True
			self.italic_widget.set_active(italics)
		if underline != self.underline_state:
			self.underline_block = True
			self.underline_widget.set_active(underline)
		if pango_font:
			self.font_widget.set_font_name (pango_font.to_string ())
		else:
			self.font_widget.set_font_name ("Sans 12")

	def translate (self, box, arg1, direction):
		self.orig_translate = [self.MainArea.translation[0], self.MainArea.translation[1]]
		if direction == "Up":
			translation_x = 0
			translation_y = 5
		elif direction == "Down":
			translation_x = 0
			translation_y = -5
		elif direction == "Right":
			translation_x = -5
			translation_y = 0
		elif direction == "Left":
			translation_x = 5
			translation_y = 0
		else:
			print "Error"
			return
		gobject.timeout_add (20, self.translate_timeout, translation_x, translation_y)
		self.tr_to = True
		
	def translate_timeout (self, addition_x, addition_y):
		if not self.tr_to:
			return False
		self.MainArea.translation[0] += addition_x / self.MainArea.scale_fac
		self.MainArea.translation[1] += addition_y / self.MainArea.scale_fac
		self.MainArea.invalidate()
		return self.tr_to

	def finish_translate (self, box, arg1):
		self.undo.add_undo (UndoManager.UndoAction (self.MainArea, UndoManager.TRANSFORM_CANVAS, \
													self.MainArea.undo_transform_cb,
													self.MainArea.scale_fac, 
													self.MainArea.scale_fac, 
													self.orig_translate,
													self.MainArea.translation))
		self.tr_to = False

	def pos_changed (self, panes, arg2):
		self.pane_pos = panes.get_position ()

	def bold_toggled (self, action):
		self.bold_state = (not self.bold_state)
		if self.bold_block:
			self.bold_block = False
			return
		if self.extended.is_focus ():
			self.extended.get_buffer().set_bold(action.get_active())
		else:
			self.MainArea.set_bold (action.get_active())

	def italic_toggled (self, action):
		self.italic_state = (not self.italic_state)
		if self.italic_block:
			self.italic_block = False
			return
		if self.extended.is_focus ():
			self.extended.get_buffer().set_italics(action.get_active())
		else:
			self.MainArea.set_italics (action.get_active())

	def underline_toggled (self, action):
		self.underline_state = (not self.underline_state)
		if self.underline_block:
			self.underline_block = False
			return
		if self.extended.is_focus ():
			self.extended.get_buffer().set_underline(action.get_active())
		else:
			self.MainArea.set_underline (action.get_active())

	def foreground_change_cb (self, button):
		if not self.extended.is_focus ():
			self.MainArea.set_foreground_color (button.get_color())

	def background_change_cb (self, button):
		if not self.extended.is_focus ():
			self.MainArea.set_background_color (button.get_color())

	def font_change_cb (self, button):
		if not self.extended.is_focus ():
			self.MainArea.set_font (button.get_font_name ())

	def zoomin_cb(self, arg):
		self.MainArea.scale_fac*=1.2
		self.MainArea.invalidate()
		
	def zoomout_cb(self, arg):
		self.MainArea.scale_fac/=1.2
		self.MainArea.invalidate()

	def new_window_cb (self, arg):
		global_new_window ()
		return

	def switch_buffer_cb (self, arg, new_buffer):
		if new_buffer:
			self.extended.set_editable (True)
			self.extended.set_buffer (new_buffer)
		else:
			self.extended.set_buffer (self.invisible_buffer)
			self.extended.set_editable (False)
			
	def thought_selected_cb (self, arg, background_color, foreground_color):
		if background_color:
			self.background_widget.set_color(background_color)
		if foreground_color:
			self.foreground_widget.set_color(foreground_color)
		
	def main_area_focus_cb (self, arg, event, extended = False):
		if not extended:
			self.MainArea.grab_focus ()
		else:
			self.extended.grab_focus ()

	def revert_mode (self, action, mode):
		self.undo.block ()
		if mode == UndoManager.UNDO:
			self.mode_request_cb (None, action.args[0])
		else:
			self.mode_request_cb (None, action.args[1])
		self.undo.unblock ()

	def mode_change_cb (self, base, activated):
		self.MainArea.set_mode (activated.get_current_value ())
		self.mode = activated.get_current_value ()
		return

	def mode_request_cb (self, widget, mode):
		if self.set_val:
			self.act.set_current_value (mode)
		else:
			pass

	def title_changed_cb (self, widget, new_title):
		self.title_cp = ''
		if new_title == '':
			self.title_cp = _('Untitled Map')
		else:
			split = new_title.splitlines ()
			if split:
				final = split.pop ()
				for s in split:
					self.title_cp += s
					self.title_cp += ' '
				self.title_cp += final
		if len(self.title_cp) > 27:
			x = self.title_cp[0:27]+"..."
			self.set_title (x)
		else:
			self.set_title (self.title_cp)
		self.emit ("title-changed", self.title_cp, self)

	def delete_cb (self, event):
		self.MainArea.delete_selected_elements ()

	def close_window_cb (self, event):
		self.SaveTimer.cancel = True
		self.hide ()
		self.MainArea.save_thyself ()
		del (self)

	def doc_del_cb (self, widget):
		self.emit ('window_closed', None)

	def serialize_to_xml(self, doc, top_element):
		top_element.setAttribute ("title", self.title_cp)
		top_element.setAttribute ("mode", str(self.mode))
		top_element.setAttribute ("size", str((self.width,self.height)))
		top_element.setAttribute ("position", str((self.xpos,self.ypos)))
		top_element.setAttribute ("maximised", str(self.maximised))
		top_element.setAttribute ("view_type", str(self.view_type))
		top_element.setAttribute ("pane_position", str(self.pane_pos))
		top_element.setAttribute ("scale_factor", str(self.MainArea.scale_fac))
		top_element.setAttribute ("translation", str(self.MainArea.translation))
		string = doc.toxml ()
		return string.encode ("utf-8" )

	def save_map(self, filename, string):
		f = file (filename, 'w')
		f.write (string)
		f.close ()

	def doc_save_cb (self, widget, doc, top_element):
		save_string = self.serialize_to_xml(doc, top_element)
		if not self.save_file:
			sham = sha.new (save_string)
			save_loc = utils.get_save_dir ()
			self.save_file = save_loc+sham.hexdigest()+".map"
			counter = 1
			while os.path.exists(self.save_file):
			
				print "Warning: Duplicate File.  Saving to alternative"
				self.save_file = save_loc + "Dup"+str(counter)+sham.hexdigest()+".map"
				counter += 1

		self.save_map(self.save_file, save_string)
		self.emit ('file_saved', self.save_file, self)

	def export_map_cb(self, event):
		chooser = gtk.FileChooserDialog(title=_("Save File As"), action=gtk.FILE_CHOOSER_ACTION_SAVE, \
										buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
		chooser.set_current_name ("%s.mapz" % self.title)
		response = chooser.run()
		if response == gtk.RESPONSE_OK:
			filename = chooser.get_filename ()
			self.MainArea.save_thyself ()
			tf = tarfile.open (filename, "w")
			tf.add (self.save_file, utils.strip_path_from_file_name(self.save_file))
			for t in self.MainArea.thoughts:
				if isinstance(t, ImageThought.ImageThought):
					tf.add (t.filename, 'images/' + utils.strip_path_from_file_name(t.filename))
					
			tf.close()

		chooser.destroy()

	def parse_file (self, filename):
		f = file (filename, 'r')
		doc = dom.parse (f)
		top_element = doc.documentElement
		self.title_cp = top_element.getAttribute ("title")
		self.mode = int (top_element.getAttribute ("mode"))
		if top_element.hasAttribute ("maximised"):
			maxi = top_element.getAttribute ("maximised")
		else:
			maxi = False
		if maxi == "True":
			self.maximize ()
		if top_element.hasAttribute ("pane_position"):
			self.pane_pos = int (top_element.getAttribute ("pane_position"))
		else:
			self.pane_pos = 500
		if top_element.hasAttribute ("view_type"):
			vt = int (top_element.getAttribute ("view_type"))
		else:
			vt = 0
		self.extended_visible = vt == 1
			
		tmp = top_element.getAttribute ("size")
		(width, height) = utils.parse_coords (tmp)
		tmp = top_element.getAttribute ("position")
		(x, y) = utils.parse_coords (tmp)
		self.resize (int (width), int (height))

		# Don't know why, but metacity seems to move the window 24 pixels
		# further down than requested.  Compensate by removing 24
		# pixels from the stored size
		y -= 24
		self.move (int (x), int (y))

		#print "Setting title"
		#self.set_title (self.title_cp)
		self.MainArea.set_mode (self.mode)
		self.MainArea.load_thyself (top_element, doc)
		if top_element.hasAttribute("scale_factor"):
			self.MainArea.scale_fac = float (top_element.getAttribute ("scale_factor"))
		if top_element.hasAttribute("translation"):
			tmp = top_element.getAttribute("translation")
			(x,y) = utils.parse_coords(tmp)
			self.MainArea.translation = [x,y]

	def configure_cb (self, window, event):
		self.xpos = event.x
		self.ypos = event.y
		self.width = event.width
		self.height = event.height
		return False

	def window_state_cb (self, window, event):
		if event.changed_mask & gtk.gdk.WINDOW_STATE_MAXIMIZED:
			self.maximised = not self.maximised

	def toggle_range (self, arg, native_width, native_height, max_width, max_height):
		if arg.get_active ():
			self.spin_width.set_value (max_width)
			self.spin_height.set_value (max_height)
			# TODO: Fix this (and below) to cope with non-native resolutions properly
			#self.spin_width.set_sensitive (True)
			#self.spin_height.set_sensitive (True)
		else:
			#self.spin_width.set_sensitive (False)
			#self.spin_height.set_sensitive (False)
			self.spin_width.set_value (native_width)
			self.spin_height.set_value (native_height)

	def export_cb (self, event):
		maxx, maxy = self.MainArea.get_max_area ()

		x, y, width, height, bitdepth = self.MainArea.window.get_geometry ()
		glade = gtk.glade.XML (utils.get_data_file_name('labyrinth.glade'))
		dialog = glade.get_widget ('ExportImageDialog')
		box = glade.get_widget ('dialog_insertion')
		fc = gtk.FileChooserWidget(gtk.FILE_CHOOSER_ACTION_SAVE)
		box.pack_end (fc)

		filter_mapping = [  (_('All Files'), ['*']),
							(_('PNG Image (*.png)'), ['*.png']),
							(_('JPEG Image (*.jpg, *.jpeg)'), ['*.jpeg', '*.jpg']),
							(_('SVG Vector Image (*.svg)'), ['*.svg']),
							(_('PDF Portable Document (*.pdf)'), ['*.pdf']) ]

		for (filter_name, filter_patterns) in filter_mapping:
			fil = gtk.FileFilter ()
			fil.set_name(filter_name)
			for pattern in filter_patterns:
				fil.add_pattern(pattern)
			fc.add_filter(fil)

		fc.set_current_name ("%s.png" % self.title)
		rad = glade.get_widget ('rb_complete_map')
		rad2 = glade.get_widget ('rb_visible_area')
		self.spin_width = glade.get_widget ('width_spin')
		self.spin_height = glade.get_widget ('height_spin')
		self.spin_width.set_value (maxx)
		self.spin_height.set_value (maxy)
		self.spin_width.set_sensitive (False)
		self.spin_height.set_sensitive (False)

		rad.connect ('toggled', self.toggle_range, width, height,maxx,maxy)

		fc.show ()
		while 1:
		# Cheesy loop.  Break out as needed.
			response = dialog.run()
			if response == gtk.RESPONSE_OK:
				ext_mime_mapping = { 'png':'png', 'jpg':'jpeg', 'jpeg':'jpeg', \
									 'svg':'svg', 'pdf':'pdf' }
				filename = fc.get_filename()
				ext = filename[filename.rfind('.')+1:]

				try:
					mime = ext_mime_mapping[ext]
					break
				except KeyError:
					msg = gtk.MessageDialog(self, gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_ERROR, gtk.BUTTONS_OK, \
											_("Unknown file format"))
					msg.format_secondary_text (_("The file type '%s' is unsupported.  Please use the suffix '.png',"\
											   " '.jpg' or '.svg'." % ext))
					msg.run ()
					msg.destroy ()
			else:
				dialog.destroy ()
				return
				
		true_width = int (self.spin_width.get_value ())
		true_height = int (self.spin_height.get_value ())
		native = not rad.get_active ()
		dialog.destroy ()

		if mime in ['png', 'jpg']:
			self.save_as_pixmap(filename, mime, true_width, true_height, bitdepth, native)
		else:
			surface = None
			if mime == 'svg': 
				surface = cairo.SVGSurface(filename, true_width, true_height)
			elif mime == 'pdf':
				surface = cairo.PDFSurface(filename, true_width, true_height)
			self.save_surface(surface, true_width, true_height, native)

	def save_as_pixmap(self, filename, mime, width, height, bitdepth, native):
		pixmap = gtk.gdk.Pixmap (None, width, height, bitdepth)
		self.MainArea.export (pixmap.cairo_create (), width, height, native)

		pb = gtk.gdk.Pixbuf.get_from_drawable(gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, width, height), \
											  pixmap, \
											  gtk.gdk.colormap_get_system(), \
											  0, 0, 0, 0, width, height)
		pb.save(filename, mime)
		
	def save_surface(self, surface, width, height, native):
		cairo_context = cairo.Context(surface)
		context = pangocairo.CairoContext(cairo_context)
		self.MainArea.export(context, width, height, native)
		surface.finish()

	def selection_changed_cb (self, area, start, end, text):
		clip = gtk.Clipboard (selection="PRIMARY")
		if text:
			clip.set_text (text)
		else:
			clip.clear ()

	def edit_activated_cb (self, menu):
			# FIXME: Keybindings should also be deactivated.
			self.cut.set_sensitive (False)
			self.copy.set_sensitive (False)
			self.paste.set_sensitive (False)
			self.link.set_sensitive (False)
			if self.extended.is_focus ():
				self.paste.set_sensitive (True)
				stend = self.extended.get_buffer().get_selection_bounds()
				if len (stend) > 1:
					start,end = stend
				else:
					start = end = stend
			else:
				start, end = self.MainArea.get_selection_bounds ()
				try:
					if self.mode == MMapArea.MODE_EDITING and len(self.MainArea.selected) and \
					   self.MainArea.selected[0].editing:
						self.paste.set_sensitive (True)
				except AttributeError:
					pass
				if len (self.MainArea.selected) == 2:
					self.link.set_sensitive (True)

			if start and start != end:
				self.cut.set_sensitive (True)
				self.copy.set_sensitive (True)

	def cut_text_cb (self, event):
		clip = gtk.Clipboard ()
		if self.extended.is_focus ():
			self.extended.get_buffer().cut_clipboard (clip)
		else:
			self.MainArea.cut_clipboard (clip)

	def copy_text_cb (self, event):
		clip = gtk.Clipboard ()
		if self.extended.is_focus ():
			self.extended.get_buffer().copy_clipboard (clip)
		else:
			self.MainArea.copy_clipboard (clip)

	def paste_text_cb (self, event):
		clip = gtk.Clipboard ()
		if self.extended.is_focus ():
			self.extended.get_buffer().paste_clipboard (clip)
		else:
			self.MainArea.paste_clipboard (clip)

	def start_timer (self):
		self.SaveTimer = PeriodicSaveThread.PeriodicSaveThread(self.MainArea)
		self.SaveTimer.setDaemon( True)
		self.SaveTimer.start()

