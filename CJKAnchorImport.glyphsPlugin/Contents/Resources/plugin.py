# encoding: utf-8

"""A Glyphs plugin to automatically place LSB/RSB/TSB/BSB anchors according to palt/vpal values when opening a font."""

import objc
from GlyphsApp import *
from GlyphsApp.plugins import *

import os
import sys
import contextlib
import collections

def use_installed_modules_when_available():
    if hasattr(Glyphs, 'versionNumber') and Glyphs.versionNumber> 2.4:
        extra_module_paths = [
            os.path.expanduser('~/Library/Application Support/Glyphs/Scripts'),
            '/Library/Application Support/Glyphs/Scripts', 
            '/Network/Library/Application Support/Glyphs/Scripts'
        ]
        for path in extra_module_paths:
            if path not in sys.path:
                if os.path.exists(path):
                    sys.path.append(path)

use_installed_modules_when_available()

from fontTools.ttLib import TTFont
from Foundation import NSBundle, NSPoint, NSEqualRects, NSZeroRect

NEEDS_APPLY_VMTX_VALUES_ON_IMPORT = True

class CJKAnchorImportPlugin(GeneralPlugin):
    
    def start(self):
        Glyphs.addCallback(self.documentOpened, DOCUMENTOPENED)
    
    def documentOpened(self, notification):
        document = notification.object()
        font = document.font
        if font.filepath:
            self.__import_anchors(font)
    
    def __import_anchors(self, font):
        with GSFontUpdatingContext(font):
            
            reader = None
            extension = os.path.splitext(font.filepath)[1].lower()
            
            if extension in ['.otf', '.ttf', '.otc', '.ttc']:
                ttfont = TTFont(font.filepath)
                if CJKAlternateMetricsGPOSReader.can_open_font(ttfont):
                    reader = CJKAlternateMetricsGPOSReader(ttfont)
            elif extension in ['.ufo']:
                reader = CJKAlternateMetricsUFOReader(font)
                
            if reader and reader.has_metrics:
                cid_rename_dict = self.__make_cid_rename_dict(font, dest='cid')
                for glyph in font.glyphs:
                    for master in font.masters:
                        layer = glyph.layers[master.id]
                        
                        offset_y = 0.0
                        vertical_metrics = reader.vmtx.get(glyph.name)
                        if not vertical_metrics and cid_rename_dict and glyph.name in cid_rename_dict:
                            vertical_metrics = reader.vmtx.get(cid_rename_dict[glyph.name])
                        if vertical_metrics:
                            layer_tsb = layer.TSB
                            if NSEqualRects(layer.bounds, NSZeroRect):
                                layer_tsb = master.ascender
                            offset_y = vertical_metrics.TSB - round(layer_tsb)
                            
                            if NEEDS_APPLY_VMTX_VALUES_ON_IMPORT:
                                if offset_y != 0.0 or vertical_metrics.height != font.upm:
                                    layer.setVertOrigin_(offset_y)
                                    layer.setVertWidth_(vertical_metrics.height)
                        
                        edge_insets = reader.edge_insets.get(glyph.name)
                        if not edge_insets and cid_rename_dict and glyph.name in cid_rename_dict:
                            edge_insets = reader.edge_insets.get(cid_rename_dict[glyph.name])
                        
                        if edge_insets:
                            center = NSPoint(layer.width / 2.0, font.upm / 2.0 + master.descender)
                            self.__clear_anchors(layer, ('LSB', 'RSB', 'TSB', 'BSB'))
                            anchor_lsb = None
                            anchor_rsb = None
                            anchor_tsb = None
                            anchor_bsb = None
                            if edge_insets.left != 0 or edge_insets.right != 0:
                                x1 = edge_insets.left
                                x2 = layer.width - edge_insets.right
                                anchor_lsb = self.__upsert_anchor(layer, 'LSB', NSPoint(x1, center.y))
                                anchor_rsb = self.__upsert_anchor(layer, 'RSB', NSPoint(x2, center.y))
                                center.x = round((x1 + x2) / 2.0)
                            if edge_insets.top != 0 or edge_insets.bottom != 0:
                                y1 = font.upm - edge_insets.top + master.descender + offset_y
                                y2 = edge_insets.bottom + master.descender + offset_y
                                anchor_tsb = self.__upsert_anchor(layer, 'TSB', NSPoint(center.x, y1))
                                anchor_bsb = self.__upsert_anchor(layer, 'BSB', NSPoint(center.x, y2))
                                center.y = round((y1 + y2) / 2.0)
                            if anchor_lsb and anchor_rsb and anchor_tsb and anchor_bsb:
                                anchor_lsb.position = NSPoint(anchor_lsb.position.x, center.y)
                                anchor_rsb.position = NSPoint(anchor_rsb.position.x, center.y)
                                anchor_tsb.position = NSPoint(center.x, anchor_tsb.position.y)
                                anchor_bsb.position = NSPoint(center.x, anchor_bsb.position.y)
                            
                        else:
                            self.__clear_anchors(layer, ('LSB', 'RSB', 'TSB', 'BSB'))
        
    def __clear_anchors(self, layer, names):
        for name in names:
            layer.removeAnchorWithName_(name)
    
    def __upsert_anchor(self, layer, name, position):
        anchor = None
        if name in layer.anchors:
            anchor = layer.anchors[name]
            anchor.position = position
        else:
            anchor = GSAnchor(name, position)
            layer.anchors.append(anchor)
        return anchor

    def __make_cid_rename_dict(self, font, dest='cid'):
        operation = objc.lookUpClass('GSExportInstanceOperation').alloc().initWithFont_instance_format_(Glyphs.font, None, 0)
        ros      = operation.CIDRescoureName()
        ro       = operation.CIDShortRescoureName()
        if ros and ro:
            filename = NSBundle.bundleWithPath_(os.path.join(NSBundle.mainBundle().builtInPlugInsPath(), 'OTF.glyphsFileFormat')).pathForResource_ofType_('MapFile{0}'.format(ro), 'txt')
            if filename:
                with open(filename, 'r') as file:
                    make_tuple = (lambda c: (c[1], 'cid{0:05d}'.format(int(c[0])))) if dest == 'cid' else (lambda c: ('cid{0:05d}'.format(int(c[0])), c[1]))
                    rename_dict = dict([make_tuple(line.split('\t')) for line in file])
                    return rename_dict
        return None
    
    def __file__(self):
        """Please leave this method unchanged"""
        return __file__


@contextlib.contextmanager
def GSFontUpdatingContext(font):
    font.disableUpdateInterface()
    try:
        yield font
    finally:
        font.enableUpdateInterface()


H = 0
V = 1
Adjustment = collections.namedtuple('Adjustment', ['glyph', 'placement', 'advance', 'direction'])
EdgeInsets = collections.namedtuple('EdgeInsets', ['left', 'right', 'top', 'bottom'])
VerticalMetrics = collections.namedtuple('VerticalMetrics', ['height', 'TSB'])

class CJKAlternateMetricsGPOSReader(object):
    
    @classmethod
    def can_open_font(cls, font):
        if font and 'GPOS' in font:
            return True
        return False
    
    def __init__(self, font):
        self.__font = font
        self.__setup(font)
    
    # - preparing lists and dictionaries
    
    def __setup(self, font):
        self.__table = None
        self.__tag_list = []
        self.__tag_lookup_dict = {}
        self.__lookup_adjustments_dict = {}
        self.__edge_insets_dict = {}
        self.__vmtx = None
        self.__vmtx_dict = {}
        if 'GPOS' in font:
            table = font['GPOS'].table
            self.__table = table
            self.__tag_list = self.__make_tag_list(table)
            self.__tag_lookup_dict = self.__make_tag_lookup_dict(table)
            self.__lookup_adjustments_dict = self.__make_lookup_adjustments_dict(table)
            self.__edge_insets_dict = self.__make_edge_insets_dict()
        if 'vmtx' in font:
            vmtx = font['vmtx']
            self.__vmtx = vmtx
            self.__vmtx_dict = self.__make_vmtx_dict()
    
    def __make_tag_list(self, table):
        l = [r.FeatureTag for r in table.FeatureList.FeatureRecord]
        s = set(l)
        return [tag for tag in sorted(s, key=lambda x: l.index(x))]
        
    def __make_tag_lookup_dict(self, table):
        d = {}
        for record in table.FeatureList.FeatureRecord:
            tag = record.FeatureTag
            if tag not in d:
                d[tag] = set([])    
            indices = record.Feature.LookupListIndex
            d[tag].update(indices)
        for tag in list(d.keys()):
            d[tag] = [table.LookupList.Lookup[i] for i in sorted(d[tag])]
        return d

    def __make_lookup_adjustments_dict(self, table):
        return dict([[lookup, self.__make_adjustments_from_lookup(lookup)] for lookup in table.LookupList.Lookup])
    
    def __make_edge_insets_from_adjustments(self, adjustments):
        placement_x, advance_x, placement_y, advance_y = (0, 0, 0, 0)
        for adjustment in adjustments:
            if adjustment.direction == H:
                placement_x += adjustment.placement
                advance_x   += adjustment.advance
            elif adjustment.direction == V:
                placement_y += adjustment.placement
                advance_y   += adjustment.advance
        return EdgeInsets(-placement_x, -(advance_x - placement_x), placement_y, -(advance_y + placement_y))
        
    def __make_edge_insets_dict(self):
        d = {}
        for tag in self.tags:
            if tag in ('palt', 'vpal'):
                for adjustment in self.adjustments_from_tag(tag):
                    if adjustment.glyph not in d:
                        d[adjustment.glyph] = []
                    d[adjustment.glyph].append(adjustment)
        for glyph in list(d.keys()):
            d[glyph] = self.__make_edge_insets_from_adjustments(d[glyph])
        return d
    
    def __make_vmtx_dict(self):
        d = {}
        if self.__vmtx:
            for key, value in self.__vmtx.metrics.items():
                d[key] = VerticalMetrics(*value)
        return d
    
    # - public methods
    
    @property
    def font(self):
        return self.__font
    
    @property
    def tags(self):
        return tuple(self.__tag_list)
    
    @property
    def has_metrics(self):
        return 'palt' in self.tags or 'vpal' in self.tags
    
    @property
    def edge_insets(self):
        return self.__edge_insets_dict
    
    @property
    def vmtx(self):
        return self.__vmtx_dict
    
    def lookups_from_tag(self, tag):
        return self.__tag_lookup_dict.get(tag, [])
    
    def adjustments_from_lookup(self, lookup):
        return self.__lookup_adjustments_dict.get(lookup, [])
    
    def adjustments_from_tag(self, tag):
        return sum([self.adjustments_from_lookup(lookup) for lookup in self.lookups_from_tag(tag)], [])
    
    # - lookup parsing
    
    def __make_adjustments_from_lookup(self, lookup):
        adjustments = []
        if lookup.LookupType == 1:
            for subtable in lookup.SubTable:
                adjustments.extend(self.__make_adjustments_from_subtable(subtable))
        return adjustments

    def __make_adjustment_from_value_in_format_1(self, glyph, value):
        return Adjustment(glyph, value.XPlacement, 0, H)
        
    def __make_adjustment_from_value_in_format_2(self, glyph, value):
        return Adjustment(glyph, value.YPlacement, 0, V)
        
    def __make_adjustment_from_value_in_format_4(self, glyph, value):
        return Adjustment(glyph, 0, value.XAdvance, H)
    
    def __make_adjustment_from_value_in_format_5(self, glyph, value):
        return Adjustment(glyph, value.XPlacement, value.XAdvance, H)
    
    def __make_adjustment_from_value_in_format_8(self, glyph, value):
        return Adjustment(glyph, 0, value.YAdvance, V)
        
    def __make_adjustment_from_value_in_format_10(self, glyph, value):
        return Adjustment(glyph, value.YPlacement, value.YAdvance, V)
    
    def __make_adjustments_from_subtable(self, subtable):
        adjustments = []
        if subtable.Format in [1, 2]:
            make_adjustment_from_value = {
                1:  self.__make_adjustment_from_value_in_format_1,
                2:  self.__make_adjustment_from_value_in_format_2,
                4:  self.__make_adjustment_from_value_in_format_4,
                5:  self.__make_adjustment_from_value_in_format_5,
                8:  self.__make_adjustment_from_value_in_format_8,
                10: self.__make_adjustment_from_value_in_format_10,
            }.get(subtable.ValueFormat)
            if make_adjustment_from_value:
                glyphs = [str(glyph) for glyph in subtable.Coverage.glyphs]
                values = self.__ensure_enumerable(subtable.Value)
                if len(glyphs) == len(values):
                    for i, value in enumerate(self.__ensure_enumerable(subtable.Value)):
                        adjustments.append(make_adjustment_from_value(glyphs[i], value))
                elif len(values) == 1:
                    value = values[-1]
                    for glyph in glyphs:
                        adjustments.append(make_adjustment_from_value(glyph, value))
        return adjustments
    
    @staticmethod
    def __ensure_enumerable(obj):
        try:
            iter(obj)
        except TypeError, te:
            return [obj]
        return obj
        
    # - 
    
    @staticmethod
    def test_drive_with_font_at_path(path):
        from pprint import pprint
        
        font = TTFont(path)
        reader = CJKAlternateMetricsGPOSReader(font)
        
        # dump tables
        for tag in reader.tags:
            print('{0}:'.format(tag))
            for adjustment in reader.adjustments_from_tag(tag):
                print('    {0}'.format(str(adjustment)))
        
        # prettification
        pprint(reader.edge_insets)


class CJKAlternateMetricsUFOReader(object):
    
    def __init__(self, font):
        self.__font = font
        self.__setup(font)
    
    def __setup(self, font):
        self.__edge_insets_dict = self.__make_edge_insets_dict()
    
    def __make_edge_insets_from_glyph(self, glyph):
        left, right, top, bottom = (0, 0, 0, 0)
        
        horizontals = []
        verticals   = []
        
        # assuming that we have only one master when imported from an ufo
        
        ascender  = glyph.parent.masters[-1].ascender
        descender = glyph.parent.masters[-1].descender
        
        guides = glyph.userData['com.typemytype.robofont.guides']
        if guides is not None:
            for guide in guides:
                angle = guide['angle']
                if angle == 90.0:
                    horizontals.append(guide['x'])
                elif angle == 0.0:
                    verticals.append(guide['y'])
        
        horizontals.sort()
        verticals.sort()
        
        if len(horizontals) >= 2:
            left = horizontals[0]
            right = glyph.layers[-1].width - horizontals[-1]
        
        if len(verticals) >= 2:
            top = ascender - verticals[-1]
            bottom = -(descender - verticals[0])
        
        if left != 0.0 or right != 0.0 or top != 0.0 or bottom != 0.0:
            return EdgeInsets(left, right, top, bottom)
        
        return None
        
    def __make_edge_insets_dict(self):
        d = {}
        for glyph in self.__font.glyphs:
            insets = self.__make_edge_insets_from_glyph(glyph)
            if insets:
                d[glyph.name] = insets
        return d
    
    # - public methods
    
    @property
    def font(self):
        return self.__font
    
    @property
    def has_metrics(self):
        return len(self.__edge_insets_dict) > 0
    
    @property
    def edge_insets(self):
        return self.__edge_insets_dict
    
    @property
    def vmtx(self):
        return {}
        
    @staticmethod
    def test_drive_with_font_at_path(path):
        from pprint import pprint
        
        font = GSFont(path)
        reader = CJKAlternateMetricsUFOReader(font)
        
        # prettification
        pprint(reader.edge_insets)
