#!/usr/bin/env python
#
# Copyright 2020 Doug Blanding (dblanding@gmail.com)
#
# This file is part of cadViewer.
# The latest  version of this file can be found at:
# //https://github.com/dblanding/cadviewer
#
# cadViewer is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# cadViewer is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# if not, write to the Free Software Foundation, Inc.
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#


from itertools import islice
import logging
import math
import os, os.path
import sys
import rpnCalculator
import stepXD
import treelib
import workplane
import bottle
from mainwindow import MainWindow, TreeView
from PyQt5.QtWidgets import QApplication, QMenu
from PyQt5.QtGui import QIcon, QPixmap, QBrush, QColor
from OCC.Core.AIS import AIS_Shape
from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCC.Core.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge,
                                     BRepBuilderAPI_MakeFace,
                                     BRepBuilderAPI_MakeSolid,
                                     BRepBuilderAPI_MakeWire,
                                     BRepBuilderAPI_Sewing,
                                     BRepBuilderAPI_Transform)
from OCC.Core.BRepFill import brepfill
from OCC.Core.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCC.Core.BRepPrimAPI import (BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism,
                                  BRepPrimAPI_MakeCylinder) 
from OCC.Core.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCC.Core.CPnts import CPnts_AbscissaPoint_Length
from OCC.Core.gp import (gp_Ax1, gp_Ax3, gp_Dir, gp_Lin, gp_Pln,
                         gp_Pnt, gp_Trsf, gp_Vec)
from OCC.Core.GC import GC_MakeSegment
from OCC.Core.GeomAPI import GeomAPI_IntSS
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.IntAna import IntAna_IntConicQuad
from OCC.Core.Interface import Interface_Static_SetCVal
from OCC.Core.Precision import precision_Angular, precision_Confusion
from OCC.Core.Prs3d import Prs3d_Drawer
from OCC.Core.STEPCAFControl import STEPCAFControl_Writer
from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCC.Core.TCollection import (TCollection_ExtendedString,
                                  TCollection_AsciiString)
from OCC.Core.TDataStd import TDataStd_Name
from OCC.Core.TDF import TDF_Label, TDF_LabelSequence
from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopoDS import (topods, TopoDS_Wire, TopoDS_Vertex, TopoDS_Edge,
                             TopoDS_Face, TopoDS_Shell, TopoDS_Solid,
                             TopoDS_Compound, TopoDS_CompSolid, topods_Edge,
                             topods_Face, topods_Shell, topods_Vertex,
                             TopoDS_Iterator)
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopTools import TopTools_ListOfShape
from OCC.Core.Quantity import (Quantity_Color, Quantity_NOC_RED,
                               Quantity_NOC_GRAY, Quantity_NOC_BLACK,
                               Quantity_NOC_DARKGREEN)
from OCC.Core.XCAFDoc import (XCAFDoc_DocumentTool_ShapeTool,
                              XCAFDoc_DocumentTool_ColorTool,
                              XCAFDoc_DocumentTool_LayerTool,
                              XCAFDoc_DocumentTool_MaterialTool,
                              XCAFDoc_ColorSurf)
from OCCUtils import Construct, Topology
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # set to DEBUG | INFO | ERROR

TOL = 1e-7 # Linear Tolerance
ATOL = TOL # Angular Tolerance
print('TOLERANCE = ', TOL)

#############################################
#
# Workplane creation functions...
#
#############################################
        
def wpBy3Pts(*args):
    """Direction from pt1 to pt2 sets wDir, pt2 is wpOrigin.
    Direction from pt2 to pt3 sets uDir."""
    print(f'args = {args}')
    if win.xyPtStack:
        # Finish
        p3 = win.xyPtStack.pop()
        p2 = win.xyPtStack.pop()
        p1 = win.xyPtStack.pop()
        wVec = gp_Vec(p1, p2)
        wDir = gp_Dir(wVec)
        origin = p2
        uVec = gp_Vec(p2, p3)
        uDir = gp_Dir(uVec)
        axis3 = gp_Ax3(origin, wDir, uDir)
        wp = workplane.WorkPlane(100, ax3=axis3)
        win.getNewPartUID(wp, typ='w')
        win.clearCallback()
        statusText = "Workplane created."
        win.statusBar().showMessage(statusText)
    else:
        # Initial setup
        win.registerCallback(wpBy3PtsC)
        display.selected_shape = None
        display.SetSelectionModeVertex()
        statusText = "Pick 3 points. Dir from pt1-pt2 sets wDir, pt2 is origin."
        win.statusBar().showMessage(statusText)
        return
        
def wpBy3PtsC(shapeList, *args):  # callback (collector) for wpBy3Pts
    print(f'args = {args}')
    add_vertex_to_xyPtStack(shapeList)
    if (len(win.xyPtStack) == 1):
        statusText = "Now select point 2 (wp origin)."
        win.statusBar().showMessage(statusText)
    elif (len(win.xyPtStack) == 2):
        statusText = "Now select point 3 to set uDir."
        win.statusBar().showMessage(statusText)
    elif (len(win.xyPtStack) == 3):
        wpBy3Pts()

def wpOnFace(*args):
    """ First face defines plane of wp. Second face defines uDir."""
    if not win.faceStack:
        win.registerCallback(wpOnFaceC)
        display.selected_shape = None
        display.SetSelectionModeFace()
        statusText = "Select face for workplane."
        win.statusBar().showMessage(statusText)
        return
    else:
        faceU = win.faceStack.pop()
        faceW = win.faceStack.pop()
        wp = workplane.WorkPlane(100, face=faceW, faceU=faceU)
        win.getNewPartUID(wp, typ='w')
        win.clearCallback()
        statusText = "Workplane created."
        win.statusBar().showMessage(statusText)
        
def wpOnFaceC(shapeList=None, *args):  # callback (collector) for wpOnFace
    if not shapeList:
        shapeList = []
    print(shapeList)
    print(args)
    for shape in shapeList:
        print(type(shape))
        face = topods_Face(shape)
        win.faceStack.append(face)
    if (len(win.faceStack) == 1):
        statusText = "Select face for workplane U direction."
        win.statusBar().showMessage(statusText)
    elif (len(win.faceStack) == 2):
        wpOnFace()

def makeWP():   # Default workplane located in X-Y plane at 0,0,0
    wp = workplane.WorkPlane(100)
    win.getNewPartUID(wp, typ='w')
    win.redraw()

#############################################
#
# 2d Construction Line functions...
# With these methods, SetSelectionModeVertex enables selection of vertexes
# on parts, automatically projecting those onto the active Workplane.
# To select intersection points on the wp, user should change to
# SetSelectionModeShape.
#
#############################################

def add_vertex_to_xyPtStack(shapeList):
    """Helper function to convert vertex to gp_Pnt and put on ptStack."""
    wp = win.activeWp
    for shape in shapeList:
        print(f"Selected item is type: {shape}")
        if isinstance(shape, TopoDS_Vertex):  # Guard against wrong type
            vrtx = topods_Vertex(shape)
            pnt = BRep_Tool.Pnt(vrtx) # convert vertex to type <gp_Pnt>
            trsf = wp.Trsf.Inverted()  # New transform. Don't invert wp.Trsf
            pnt.Transform(trsf)
            pt2d = (pnt.X(), pnt.Y())  # 2d point
            win.xyPtStack.append(pt2d)
        else:
            print(f"(Unwanted) shape type: {type(shape)}")

def processLineEdit():
    """pop value from lineEditStack and place on floatStack or ptStack."""

    text = win.lineEditStack.pop()
    if ',' in text:
        try:
            xstr , ystr = text.split(',')
            p = (float(xstr) * win.unitscale, float(ystr) * win.unitscale)
            win.xyPtStack.append(p)
        except :
            print("Problem with processing line edit stack")
    else:
        try:
            win.floatStack.append(float(text))
        except ValueError as e:
            print(f"{e}")
    

def clineH():   # Horizontal construction line
    if win.xyPtStack:
        wp = win.activeWp
        p = win.xyPtStack.pop()
        win.xyPtStack = []
        wp.hcl(p)
        win.redraw()
    else:
        win.registerCallback(clineHC)
        display.SetSelectionModeVertex()
        win.xyPtStack = []
        win.clearLEStack()
        win.lineEdit.setFocus()
        statusText = "Select point or enter Y-value for horizontal cline."
        win.statusBar().showMessage(statusText)

def clineHC(shapeList, *args):  # callback (collector) for clineH
    add_vertex_to_xyPtStack(shapeList)
    if win.lineEditStack:
        processLineEdit()
    if win.floatStack:
        y = win.floatStack.pop() * win.unitscale
        pnt = (0, y)
        win.xyPtStack.append(pnt)
    if win.xyPtStack:
        clineH()

def clineV():   # Vertical construction line
    if win.xyPtStack:
        wp = win.activeWp
        p = win.xyPtStack.pop()
        win.xyPtStack = []
        wp.vcl(p)
        win.redraw()
    else:
        win.registerCallback(clineVC)
        display.SetSelectionModeVertex()
        win.xyPtStack = []
        win.clearLEStack()
        win.lineEdit.setFocus()
        statusText = "Select point or enter X-value for vertcal cline."
        win.statusBar().showMessage(statusText)

def clineVC(shapeList, *args):  # callback (collector) for clineV
    add_vertex_to_xyPtStack(shapeList)
    if win.lineEditStack:
        processLineEdit()
    if win.floatStack:
        x = win.floatStack.pop() * win.unitscale
        pnt = (x, 0)
        win.xyPtStack.append(pnt)
    if win.xyPtStack:
        clineV()

def clineHV():   # Horizontal + Vertical construction lines
    if win.xyPtStack:
        wp = win.activeWp
        p = win.xyPtStack.pop()
        win.xyPtStack = []
        wp.hvcl(p)
        win.redraw()
    else:
        win.registerCallback(clineHVC)
        display.SetSelectionModeVertex()
        win.xyPtStack = []
        win.clearLEStack()
        win.lineEdit.setFocus()
        statusText = "Select point or enter x,y coords for H+V cline."
        win.statusBar().showMessage(statusText)

def clineHVC(shapeList, *args):  # callback (collector) for clineHV
    add_vertex_to_xyPtStack(shapeList)
    if win.lineEditStack:
        processLineEdit()
    if win.xyPtStack:
        clineHV()

def cline2Pts():
    if len(win.xyPtStack) == 2:
        wp = win.activeWp
        p2 = win.xyPtStack.pop()
        p1 = win.xyPtStack.pop()
        wp.acl(p1, p2)
        win.xyPtStack = []
        win.redraw()
    else:
        win.registerCallback(cline2PtsC)
        display.SetSelectionModeVertex()
        win.xyPtStack = []
        win.clearLEStack()
        win.lineEdit.setFocus()
        statusText = "Select 2 points for Construction Line."
        win.statusBar().showMessage(statusText)

def cline2PtsC(shapeList, *args):  # callback (collector) for cline2Pts
    add_vertex_to_xyPtStack(shapeList)
    if win.lineEditStack:
        processLineEdit()
    if len(win.xyPtStack) == 2:
        cline2Pts()

def clineAng():
    if (win.xyPtStack and win.floatStack):
        wp = win.activeWp
        text = win.floatStack.pop()
        angle = float(text)
        pnt = win.xyPtStack.pop()
        wp.acl(pnt, ang=angle)
        win.xyPtStack = []
        win.redraw()
    else:
        win.registerCallback(clineAngC)
        display.SetSelectionModeVertex()
        win.xyPtStack = []
        win.floatStack = []
        win.lineEditStack = []
        win.lineEdit.setFocus()
        statusText = "Select point on WP (or enter x,y coords) then enter angle."
        win.statusBar().showMessage(statusText)

def clineAngC(shapeList, *args):  # callback (collector) for clineAng
    add_vertex_to_xyPtStack(shapeList)
    win.lineEdit.setFocus()
    if win.lineEditStack:
        processLineEdit()
    if (win.xyPtStack and win.floatStack):
        clineAng()

def clineRefAng():
    pass

def clineAngBisec():
    pass

def clineLinBisec():
    if len(win.xyPtStack) == 2:
        wp = win.activeWp
        pnt2 = win.xyPtStack.pop()
        pnt1 = win.xyPtStack.pop()
        wp.lbcl(pnt1, pnt2)
        win.xyPtStack = []
        win.redraw()
    else:
        win.registerCallback(clineLinBisecC)
        display.SetSelectionModeVertex()

def clineLinBisecC(shapeList, *args):  # callback (collector) for clineLinBisec
    add_vertex_to_xyPtStack(shapeList)
    if len(win.xyPtStack) == 2:
        clineLinBisec()

def clinePara():
    pass

def clinePerp():
    pass

def clineTan1():
    pass

def clineTan2():
    pass

def ccirc():
    """Create a c-circle from center & radius or center & Pnt on circle."""
    wp = win.activeWp
    if len(win.xyPtStack) == 2:
        p2 = win.xyPtStack.pop()
        p1 = win.xyPtStack.pop()
        rad = wp.p2p_dist(p1, p2)
        wp.circle(p1, rad, constr=True)
        win.xyPtStack = []
        win.floatStack = []
        win.redraw()
    elif (win.xyPtStack and win.floatStack):
        pnt = win.xyPtStack.pop()
        rad = win.floatStack.pop() * win.unitscale
        wp.circle(pnt, rad, constr=True)
        win.xyPtStack = []
        win.floatStack = []
        win.redraw()
    else:
        win.registerCallback(ccircC)
        display.SetSelectionModeVertex()
        win.xyPtStack = []
        win.floatStack = []
        win.lineEditStack = []
        win.lineEdit.setFocus()
        statusText = "Pick center of construction circle and enter radius."
        win.statusBar().showMessage(statusText)

def ccircC(shapeList, *args):
    """callback (collector) for ccirc"""
    add_vertex_to_xyPtStack(shapeList)
    win.lineEdit.setFocus()
    if win.lineEditStack:
        processLineEdit()
    if len(win.xyPtStack) == 2:
        ccirc()
    if (win.xyPtStack and win.floatStack):
        ccirc()

#############################################
#
# 2d Profile Geometry functions...
#
#############################################

def line():
    """Create a profile geometry line between two end points."""
    if len(win.xyPtStack) == 2:
        wp = win.activeWp
        pnt2 = win.xyPtStack.pop()
        pnt1 = win.xyPtStack.pop()
        wp.line(pnt1, pnt2)
        win.xyPtStack = []
        win.redraw()
    else:
        win.registerCallback(lineC)
        display.SetSelectionModeVertex()
        win.xyPtStack = []
        win.lineEdit.setFocus()
        statusText = "Select 2 end points for line."
        win.statusBar().showMessage(statusText)

def lineC(shapeList, *args):
    """callback (collector) for line"""
    add_vertex_to_xyPtStack(shapeList)
    win.lineEdit.setFocus()
    if win.lineEditStack:
        processLineEdit()
    if len(win.xyPtStack) == 2:
        line()

def rect():
    """Create a profile geometry rectangle from two diagonally opposite corners."""
    if len(win.xyPtStack) == 2:
        wp = win.activeWp
        pnt2 = win.xyPtStack.pop()
        pnt1 = win.xyPtStack.pop()
        wp.rect(pnt1, pnt2)
        win.xyPtStack = []
        win.redraw()
    else:
        win.registerCallback(rectC)
        display.SetSelectionModeVertex()
        win.xyPtStack = []
        win.lineEdit.setFocus()
        statusText = "Select 2 points for Rectangle."
        win.statusBar().showMessage(statusText)

def rectC(shapeList, *args):
    """callback (collector) for rect"""
    add_vertex_to_xyPtStack(shapeList)
    win.lineEdit.setFocus()
    if win.lineEditStack:
        processLineEdit()
    if len(win.xyPtStack) == 2:
        rect()

def circle():
    """Create a geometry circle from cntr & rad or cntr & pnt on circle."""
    wp = win.activeWp
    if len(win.xyPtStack) == 2:
        p2 = win.xyPtStack.pop()
        p1 = win.xyPtStack.pop()
        rad = wp.p2p_dist(p1, p2)
        wp.circle(p1, rad, constr=False)
        win.xyPtStack = []
        win.floatStack = []
        win.redraw()
    elif (win.xyPtStack and win.floatStack):
        pnt = win.xyPtStack.pop()
        rad = win.floatStack.pop() * win.unitscale
        wp.circle(pnt, rad, constr=False)
        win.xyPtStack = []
        win.floatStack = []
        win.redraw()
    else:
        win.registerCallback(circleC)
        display.SetSelectionModeVertex()
        win.xyPtStack = []
        win.floatStack = []
        win.lineEditStack = []
        win.lineEdit.setFocus()
        statusText = "Pick center and enter radius or pick center & 2nd point."
        win.statusBar().showMessage(statusText)

def circleC(shapeList, *args):
    """callback (collector) for circle"""
    add_vertex_to_xyPtStack(shapeList)
    win.lineEdit.setFocus()
    if win.lineEditStack:
        processLineEdit()
    if len(win.xyPtStack) == 2:
        circle()
    if (win.xyPtStack and win.floatStack):
        circle()

def arcc2p():
    """Create an arc from center pt, start pt and end pt."""
    wp = win.activeWp
    if len(win.xyPtStack) == 3:
        pe = win.xyPtStack.pop()
        ps = win.xyPtStack.pop()
        pc = win.xyPtStack.pop()
        wp.arcc2p(pc, ps, pe)
        win.xyPtStack = []
        win.floatStack = []
        win.redraw()
    else:
        win.registerCallback(arcc2pC)
        display.SetSelectionModeVertex()
        win.xyPtStack = []
        statusText = "Pick center of arc, then start then end point."
        win.statusBar().showMessage(statusText)


def arcc2pC(shapeList, *args):
    """callback (collector) for circle"""
    add_vertex_to_xyPtStack(shapeList)
    win.lineEdit.setFocus()
    if win.lineEditStack:
        processLineEdit()
    if len(win.xyPtStack) == 3:
        arcc2p()

def arc3p():
    """Create an arc from start pt, end pt, and 3rd pt on the arc."""
    pass

def geom():
    pass

#############################################
#
# 3D Geometry creation functions...
#
#############################################

def makeBox():
    name = 'Box'
    myBody = BRepPrimAPI_MakeBox(60,60,50).Shape()
    uid = win.getNewPartUID(myBody, name=name)
    win.redraw()
    
def makeCyl():
    name = 'Cylinder'
    myBody = BRepPrimAPI_MakeCylinder(40,80).Shape()
    uid = win.getNewPartUID(myBody, name=name)
    win.redraw()
    
def extrude():
    """Extrude profile on active WP to create a new part."""
    wp = win.activeWp
    if len(win.lineEditStack) == 2:
        name = win.lineEditStack.pop()
        length = float(win.lineEditStack.pop()) * win.unitscale
        wire = wp.makeWire()
        myFaceProfile = BRepBuilderAPI_MakeFace(wire)
        if myFaceProfile.IsDone():
            bottomFace = myFaceProfile.Face()
        aPrismVec = wp.wVec * length
        myBody = BRepPrimAPI_MakePrism(myFaceProfile.Shape(),
                                       aPrismVec).Shape()
        uid = win.getNewPartUID(myBody, name=name)
        win.redraw()
    else:
        win.registerCallback(extrudeC)
        win.lineEdit.setFocus()
        statusText = "Enter extrusion length, then enter part name."
        win.statusBar().showMessage(statusText)

def extrudeC(shapeList, *args):
    win.lineEdit.setFocus()
    if len(win.lineEditStack) == 2:
        extrude()


#############################################
#
# 3D Geometry positioning functons...
#
#############################################

def rotateAP():
    aisShape = AIS_Shape(win.activePart)
    ax1 = gp_Ax1(gp_Pnt(0., 0., 0.), gp_Dir(1., 0., 0.))
    aRotTrsf = gp_Trsf()
    angle = math.pi/18 # 10 degrees
    aRotTrsf.SetRotation(ax1, angle)
    aTopLoc = TopLoc_Location(aRotTrsf)
    win.activePart.Move(aTopLoc)
    win.redraw()
    return

#############################################
#
# 3D Geometry modification functons...
#
#############################################

def fillet(event=None):
    if (win.lineEditStack and win.edgeStack):
        text = win.lineEditStack.pop()
        filletR = float(text) * win.unitscale
        edges = []
        for edge in win.edgeStack:
            edges.append(edge)
        win.edgeStack = []
        workPart = win.activePart
        wrkPrtUID = win.activePartUID
        mkFillet = BRepFilletAPI_MakeFillet(workPart)
        for edge in edges:
            mkFillet.Add(filletR , edge)
        newPart = mkFillet.Shape()
        win.getNewPartUID(newPart, ancestor=wrkPrtUID)
        win.statusBar().showMessage('Fillet operation complete')
        win.clearCallback()
    else:
        win.registerCallback(filletC)
        display.SetSelectionModeEdge()
        statusText = "Select edge(s) to fillet then specify fillet radius."
        win.statusBar().showMessage(statusText)
        
def filletC(shapeList, *args):  # callback (collector) for fillet
    print(shapeList)
    print(args)
    win.lineEdit.setFocus()
    for shape in shapeList:
        edge = topods_Edge(shape)
        win.edgeStack.append(edge)
    if (win.edgeStack and win.lineEditStack):
        fillet()

def shell(event=None):
    if (win.lineEditStack and win.faceStack):
        text = win.lineEditStack.pop()
        faces = TopTools_ListOfShape()
        for face in win.faceStack:
            faces.Append(face)
        win.faceStack = []
        workPart = win.activePart
        wrkPrtUID = win.activePartUID
        shellT = float(text) * win.unitscale
        newPart = BRepOffsetAPI_MakeThickSolid(workPart, faces, -shellT, 1.e-3).Shape()
        win.getNewPartUID(newPart, ancestor=wrkPrtUID)
        win.statusBar().showMessage('Shell operation complete')
        win.clearCallback()
    else:
        win.registerCallback(shellC)
        display.SetSelectionModeFace()
        statusText = "Select face(s) to remove then specify shell thickness."
        win.statusBar().showMessage(statusText)

def shellC(shapeList, *args):  # callback (collector) for shell
    print(shapeList)
    print(args)
    win.lineEdit.setFocus()
    for shape in shapeList:
        face = topods_Face(shape)
        win.faceStack.append(face)
    if (win.faceStack and win.lineEditStack):
        shell()

#####################
#                   #
#   Bottle Demo:    #
#                   #
#####################

# Make Bottle step by step...   
def makePoints(event=None):
    V1, V2, V3, V4, V5, V6 = bottle.makePoints()  # gp_Pnt
    display.DisplayShape(V1.Vertex())
    display.DisplayShape(V2.Vertex())
    display.DisplayShape(V3.Vertex())
    display.DisplayShape(V4.Vertex())
    display.DisplayShape(V5.Vertex())
    display.DisplayShape(V6.Vertex())
    display.FitAll()
    display.EraseAll()
    display.DisplayShape(V1.Vertex())
    display.DisplayShape(V2.Vertex())
    display.DisplayShape(V3.Vertex())
    display.DisplayShape(V4.Vertex())
    display.DisplayShape(V5.Vertex())
    display.Repaint()
    win.statusBar().showMessage('Make Points complete')

def makeLines(event=None):
    e1, e2, e3 = bottle.makeLines()  # TopoDS_Edge
    display.DisplayColoredShape(e1,'RED')
    display.DisplayColoredShape(e2,'RED')
    display.DisplayColoredShape(e3,'RED')
    display.Repaint()
    win.statusBar().showMessage('Make lines complete')

def makeHalfWire(event=None):
    aWire  = bottle.makeHalfWire()  # TopoDS_Wire
    display.EraseAll()
    display.DisplayColoredShape(aWire, 'BLUE')
    display.Repaint()
    win.statusBar().showMessage('Make Half Wire complete')

def makeWholeWire(event=None):
    myWireProfile = bottle.makeWholeWire()  # TopoDS_Wire
    display.DisplayColoredShape(myWireProfile, 'BLUE')
    display.Repaint()
    win.statusBar().showMessage('Make whole wire complete')

def makeFace(event=None):
    bottomFace = bottle.makeFace()  # TopoDS_Face
    display.DisplayShape(bottomFace, color='YELLOW', transparency=0.6)
    display.Repaint()
    win.statusBar().showMessage('Make face complete')

def makeBody(event=None):
    myBody = bottle.makeBody()  # TopoDS_Shape
    partName = 'body'
    win.getNewPartUID(myBody, name=partName)
    win.statusBar().showMessage('Bottle body complete')
    win.redraw()

def makeFillets(event=None):
    workPart = win.activePart
    wrkPrtUID = win.activePartUID
    newPrtName = 'bodyWithFillets'
    mkFillet = BRepFilletAPI_MakeFillet(workPart)
    aEdgeExplorer = TopExp_Explorer(workPart, TopAbs_EDGE)
    while aEdgeExplorer.More():
        aEdge = topods_Edge(aEdgeExplorer.Current())
        mkFillet.Add(bottle.thickness / 12. , aEdge)
        aEdgeExplorer.Next()
    myBody = mkFillet.Shape()
    win.getNewPartUID(myBody, name=newPrtName, ancestor=wrkPrtUID)
    win.statusBar().showMessage('Bottle with fillets complete')
    win.redraw()

def addNeck(event=None):
    newPrtName = 'bodyWithNeck'
    workPart = win.activePart
    wrkPrtUID = win.activePartUID
    myNeck = bottle.addNeck()  # TopoDS_Shape
    myBody = BRepAlgoAPI_Fuse(workPart, myNeck).Shape()
    win.getNewPartUID(myBody, name=newPrtName, ancestor=wrkPrtUID)
    win.statusBar().showMessage('Add neck complete')
    win.redraw()

#############################################
#
#  Info & Utility functions:
#
#############################################

def topoDumpAP():
    Topology.dumpTopology(win.activePart)
        
def printCurrUID():
    print(win._currentUID)

def printActiveAsyInfo():
    print(f"Name: {win.activeAsy}")
    print(f"UID: {win.activeAsyUID}")

def printActiveWpInfo():
    print(f"Name: {win.activeWp}")
    print(f"UID: {win.activeWpUID}")

def printActivePartInfo():
    print(f"Name: {win.activePart}")
    print(f"UID: {win.activePartUID}")

def printPartsInActiveAssy():
    asyPrtTree = []
    leafNodes = win.treeModel.leaves(self.activeAsyUID)
    for node in leafNodes:
        pid = node.identifier
        if pid in win._partDict:
            asyPrtTree.append(pid)
    print(asyPrtTree)

def printActPart():
    uid = win.activePartUID
    if uid:
        name = win._nameDict[uid]
        print("Active Part: %s [uid=%i]" % (name, int(uid)))
    else:
        print(None)

def printTreeView():
    """Print 'uid'; 'name'; 'parent' for all items in treeView."""
    iterator = QTreeWidgetItemIterator(win.treeView)
    while iterator.value():
        item = iterator.value()
        name = item.text(0)
        strUID = item.text(1)
        uid = int(strUID)
        pname = None
        parent = item.parent()
        if parent:
            puid = parent.text(1)
            pname = parent.text(0)
        print(f"UID: {uid}; Name: {name}; Parent: {pname}")
        iterator += 1

def clearPntStack():
    win.xyPtStack = []

def printDrawList():
    print("Draw List:", win.drawList)

def printInSync():
    print(win.inSync())
        
def setUnits_in():
    win.setUnits('in')
        
def setUnits_mm():
    win.setUnits('mm')

if __name__ == '__main__':        
    app = QApplication(sys.argv)
    win = MainWindow()
    win.add_menu('File')
    win.add_function_to_menu('File', "Load STEP", win.loadStep)
    win.add_function_to_menu('File', "Save STEP", win.saveStep)
    win.add_function_to_menu('File', "Save STEP (Act Prt)", win.saveStepActPrt)
    win.add_menu('Workplane')
    win.add_function_to_menu('Workplane', "Workplane on face", wpOnFace)
    win.add_function_to_menu('Workplane', "Workplane by 3 points", wpBy3Pts)
    win.add_function_to_menu('Workplane', "(Def) Workplane @Z=0", makeWP)
    win.add_menu('Create 3D')
    win.add_function_to_menu('Create 3D', "Box", makeBox)
    win.add_function_to_menu('Create 3D', "Cylinder", makeCyl)
    win.add_function_to_menu('Create 3D', "extrude", extrude)
    win.add_menu('Modify Active Part')
    win.add_function_to_menu('Modify Active Part', "Rotate Act Part", rotateAP)
    win.add_function_to_menu('Modify Active Part', "Fillet", fillet)
    win.add_function_to_menu('Modify Active Part', "Shell", shell)
    # excised dynamic3Dmodification functions
    #win.add_function_to_menu('Modify Active Part', "Lift Face", lift)
    #win.add_function_to_menu('Modify Active Part', "Offset Face", offsetFace)
    #win.add_function_to_menu('Modify Active Part', "Align Face", alignFace)
    #win.add_function_to_menu('Modify Active Part', "Tweak Face", tweakFace)
    #win.add_function_to_menu('Modify Active Part', "Fuse", fuse)
    #win.add_function_to_menu('Modify Active Part', "Remove Face", remFace)
    win.add_menu('Bottle')
    win.add_function_to_menu('Bottle', "Step 1: points", makePoints)
    win.add_function_to_menu('Bottle', "Step 2: lines", makeLines)
    win.add_function_to_menu('Bottle', "Step 3: half wire", makeHalfWire)
    win.add_function_to_menu('Bottle', "Step 4: whole wire", makeWholeWire)
    win.add_function_to_menu('Bottle', "Step 5: face", makeFace)
    win.add_function_to_menu('Bottle', "Step 6: body", makeBody)
    win.add_function_to_menu('Bottle', "Step 7: fillets", makeFillets)
    win.add_function_to_menu('Bottle', "Step 8: neck", addNeck)
    win.add_menu('Utility')
    win.add_function_to_menu('Utility', "Topology of Act Prt", topoDumpAP)
    win.add_function_to_menu('Utility', "print(current UID)", printCurrUID)
    win.add_function_to_menu('Utility', "print(TreeViewData)", printTreeView)
    win.add_function_to_menu('Utility', "print(Active Wp Info)", printActiveWpInfo)
    win.add_function_to_menu('Utility', "print(Active Asy Info)", printActiveAsyInfo)
    win.add_function_to_menu('Utility', "print(Active Prt Info)", printActivePartInfo)
    win.add_function_to_menu('Utility', "Clear Line Edit Stack", win.clearLEStack)
    win.add_function_to_menu('Utility', "Calculator", win.launchCalc)
    win.add_function_to_menu('Utility', "set Units ->in", setUnits_in)
    win.add_function_to_menu('Utility', "set Units ->mm", setUnits_mm)

    drawSubMenu = QMenu('Draw')
    win.popMenu.addMenu(drawSubMenu)    
    drawSubMenu.addAction('Fit All', win.fitAll)    
    drawSubMenu.addAction('Redraw', win.redraw)    
    drawSubMenu.addAction('Hide All', win.eraseAll)    
    drawSubMenu.addAction('Draw All', win.drawAll)    
    drawSubMenu.addAction('Draw Only Active Part', win.drawOnlyActivePart)

    win.treeView.popMenu.addAction('Set Active', win.setClickedActive)
    win.treeView.popMenu.addAction('Make Transparent', win.setTransparent)
    win.treeView.popMenu.addAction('Make Opaque', win.setOpaque)
    win.treeView.popMenu.addAction('Edit Name', win.editName)

    win.show()
    win.canva.InitDriver()
    display = win.canva._display

    selectSubMenu = QMenu('Select Mode')
    win.popMenu.addMenu(selectSubMenu)    
    selectSubMenu.addAction('Vertex', display.SetSelectionModeVertex)    
    selectSubMenu.addAction('Edge', display.SetSelectionModeEdge)    
    selectSubMenu.addAction('Face', display.SetSelectionModeFace)    
    selectSubMenu.addAction('Shape', display.SetSelectionModeShape)    
    selectSubMenu.addAction('Neutral', display.SetSelectionModeNeutral)    
    win.popMenu.addAction('Clear Callback', win.clearCallback)
    # Toolbar buttons
    win.wcToolBar.addAction(QIcon(QPixmap('icons/hcl.gif')), 'Horizontal', clineH)
    win.wcToolBar.addAction(QIcon(QPixmap('icons/vcl.gif')), 'Vertical', clineV)
    win.wcToolBar.addAction(QIcon(QPixmap('icons/hvcl.gif')), 'H + V', clineHV)
    win.wcToolBar.addAction(QIcon(QPixmap('icons/tpcl.gif')), 'By 2 Pnts', cline2Pts)
    win.wcToolBar.addAction(QIcon(QPixmap('icons/acl.gif')), 'Angle', clineAng)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/refangcl.gif')), 'Ref-Ang', clineRefAng)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/abcl.gif')), 'Angular Bisector', clineAngBisec)
    win.wcToolBar.addAction(QIcon(QPixmap('icons/lbcl.gif')), 'Linear Bisector', clineLinBisec)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/parcl.gif')), 'Parallel', clinePara)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/perpcl.gif')), 'Perpendicular', clinePerp)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/cltan1.gif')), 'Tangent to circle', clineTan1)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/cltan2.gif')), 'Tangent 2 circles', clineTan2)
    win.wcToolBar.addAction(QIcon(QPixmap('icons/ccirc.gif')), 'Circle', ccirc)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/cc3p.gif')), 'Circle by 3Pts', ccirc)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/cccirc.gif')), 'Concentric Circle', ccirc)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/cctan2.gif')), 'Circ Tangent x2', ccirc)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/cctan3.gif')), 'Circ Tangent x3', ccirc)
    win.wcToolBar.addSeparator()
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/del_c.gif')), 'Delete Constr', geom)
    #win.wcToolBar.addAction(QIcon(QPixmap('icons/del_el.gif')), 'Delete Constr', geom)

    win.wgToolBar.addAction(QIcon(QPixmap('icons/line.gif')), 'Line', line)
    win.wgToolBar.addAction(QIcon(QPixmap('icons/rect.gif')), 'Rectangle', rect)
    #win.wgToolBar.addAction(QIcon(QPixmap('icons/poly.gif')), 'Polygon', geom)
    #win.wgToolBar.addAction(QIcon(QPixmap('icons/slot.gif')), 'Slot', geom)
    win.wgToolBar.addAction(QIcon(QPixmap('icons/circ.gif')), 'Circle', circle)
    win.wgToolBar.addAction(QIcon(QPixmap('icons/arcc2p.gif')), 'Arc Cntr-2Pts', arcc2p)
    #win.wgToolBar.addAction(QIcon(QPixmap('icons/arc3p.gif')), 'Arc by 3Pts', arc3p)
    win.wgToolBar.addSeparator()
    #win.wgToolBar.addAction(QIcon(QPixmap('icons/translate.gif')), 'Translate Profile', geom)
    #win.wgToolBar.addAction(QIcon(QPixmap('icons/rotate.gif')), 'Rotate Profile', geom)
    #win.wgToolBar.addAction(QIcon(QPixmap('icons/del_g.gif')), 'Delete Profile', geom)

    win.raise_() # bring the app to the top
    app.exec_()
