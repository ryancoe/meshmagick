#!/usr/bin/env python
# -*- coding: utf-8 -*-
# PYTHON_ARGCOMPLTETE_OK

# Python module to manipulate 2D meshes for hydrodynamics purposes

"""
This module contains utility function to manipulate, load, save and
convert mesh files
Two numpy arrays are manipulated in this module : V and F.
V is the array of nodes coordinates. It is an array of shape (nv, 3) where
nv is the number of nodes in the mesh.
F is the array of cell connectivities. It is an array of shape (nf, 4) where
nf is the number of cells in the mesh. Not that it has 4 columns as we consider
flat polygonal cells up to 4 edges (quads). Triangles are obtained by repeating
the first node at the end of the cell node ID list.

ATTENTION : IDs of vertices should always start at 1, which is the usual case in
file formats. However, for VTK, it starts at 0. To avoid confusion, we should
always start at 1 and do the appropriated conversions on F.
"""

import os, sys
import numpy as np

__author__ = "Francois Rongere"
__copyright__ = "Copyright 2014-2015, Ecole Centrale de Nantes"
__credits__ = "Francois Rongere"
__licence__ = "CeCILL"
__version__ = "0.3.1"
__maintainer__ = "Francois Rongere"
__email__ = "Francois.Rongere@ec-nantes.fr"
__status__ = "Development"

real_str = r'[+-]?(?:\d+\.\d*|\d*\.\d+)(?:[Ee][+-]?\d+)?'

import numpy as np
import math

# Classes
class Plane:
    def __init__(self, normal=np.array([0., 0., 1.]), e=0.):
        self.normal = normal
        self.e = e

    def flip(self):
        self.normal = -self.normal

    def set_position(self, z=0., phi=0., theta=0.):
        """Performs the transformation of the plane"""

        # Rotation matrix
        cphi = math.cos(phi)
        sphi = math.sin(phi)
        ctheta = math.cos(theta)
        stheta = math.sin(theta)

        self.normal = np.array([stheta*cphi, -sphi, ctheta*cphi])
        self.e = z * self.normal[-1]

    def point_distance(self, point, tol=1e-9):
        dist = np.dot(self.normal, point)
        if math.fabs(dist) < tol:
            # Point on plane
            position = 0
        elif dist < self.e:
            # Point under plane
            position = -1
        elif dist > self.e:
            # Point above plane
            position = 1
        return dist, position


def clip_by_plane(V, F, plane, abs_tol=1e-3, get_polygon=False, areas=None):

    n_threshold = 5 # devrait etre reglagble, non utilise pour le moment

    # TODO : Partir d'un F indice utilisant des indices de vertex commencant a 0 (F -=1)

    # Necessary to deal with clipping of quadrangle that give a pentagon
    triangle = [2, 3, 4, 2]
    quadrangle = [1, 2, 4, 5]

    # Classification of vertices
    nv = V.shape[0]
    nf = F.shape[0]

    # Getting the position of each vertex with respect to the plane (projected distance)
    positions = np.dot(V, plane.normal)-plane.e

    # Getting the vertices we are sure to keep
    keepV = positions <= abs_tol # Vertices we know we will keep

    # If the mesh is totally at one side of the plane, no need to go further !
    nb_kept_V = np.sum(keepV)
    if nb_kept_V == nv:
        return V, F
    elif nb_kept_V == 0:
        return [], []

    # Getting triangles and quads masks
    triangle_mask = F[:,0] == F[:,-1]
    nb_triangles = np.sum(triangle_mask)
    quad_mask = np.invert(triangle_mask)
    nb_quads = nf-nb_triangles

    # Getting the number of kept vertex by face
    nb_V_kept_by_face = np.zeros(nf, dtype=np.int32)
    nb_V_kept_by_face[triangle_mask] = \
        np.sum(keepV[(F[triangle_mask,:3]-1).flatten()].reshape((nb_triangles, 3)), axis=1)
    nb_V_kept_by_face[quad_mask] = \
        np.sum(keepV[(F[quad_mask]-1).flatten()].reshape((nb_quads, 4)), axis=1)

    # Getting the number of vertex below the plane by face
    nb_V_below_by_face = np.zeros(nf, dtype=np.int32)
    V_below_mask = positions < -abs_tol
    nb_V_below_by_face[triangle_mask] = np.sum(V_below_mask[(F[triangle_mask,:3]-1).flatten()].reshape(nb_triangles,
                                                                                                       3), axis=1)
    nb_V_below_by_face[quad_mask] = np.sum(V_below_mask[(F[quad_mask]-1).flatten()].reshape(nb_quads, 4), axis=1)

    # Getting the faces that are kept as every of their vertices are kept
    keepF = np.zeros(nf, dtype=bool)
    keepF[np.logical_and(triangle_mask, nb_V_kept_by_face == 3)] = True
    keepF[np.logical_and(quad_mask, nb_V_kept_by_face == 4)] = True

    if get_polygon:
        # Getting the vertices that are already on the boundary
        boundary_V_mask = np.fabs(positions)<=abs_tol # Vertices that are already on the boundary

        # Getting the boundary faces
        nb_V_on_boundary_by_face = np.zeros(nf, dtype=np.int32)
        nb_V_on_boundary_by_face[triangle_mask] = \
            np.sum(boundary_V_mask[(F[triangle_mask,:3]-1).flatten()].reshape((nb_triangles, 3)), axis=1)
        nb_V_on_boundary_by_face[quad_mask] = \
            np.sum(boundary_V_mask[(F[quad_mask]-1).flatten()].reshape((nb_quads, 4)), axis=1)


        # Faces that are at the boundary but that have to be clipped, sharing an edge with the boundary
        boundary_faces_mask = np.zeros(nf, dtype=bool)
        boundary_faces_mask[triangle_mask] =  np.logical_and(nb_V_on_boundary_by_face[triangle_mask] == 2,
                                                             nb_V_kept_by_face[triangle_mask] == 3)
        boundary_faces_mask[quad_mask] =  np.logical_and(nb_V_on_boundary_by_face[quad_mask] == 2,
                                                             nb_V_kept_by_face[quad_mask] == 4)

        # Building the boundary edges that are formed by the boundary_vertices
        # boundary_faces = np.array([i for i in xrange(nf)])[boundary_faces_mask]
        boundary_faces = np.arange(nf)[boundary_faces_mask]
        boundary_edges = {}
        for face in F[boundary_faces]-1:
            # TODO : continuer ICI l'implementation
            if face[0] == face[-1]:
                face_w = face[:3]
            else:
                face_w = face
            boundary_V_face_mask = boundary_V_mask[face_w]
            for (index, is_V_on_boundary) in enumerate(boundary_V_face_mask):
                if is_V_on_boundary:
                    if boundary_V_face_mask[index-1]:
                        boundary_edges[face_w[index]] = face_w[index-1]
                    else:
                        boundary_edges[face_w[index+1]] = face_w[index]
                    break

    clipped_mask = np.zeros(nf, dtype=bool)
    clipped_mask[triangle_mask] = np.logical_and(nb_V_kept_by_face[triangle_mask] < 3,
                                                 nb_V_below_by_face[triangle_mask] > 0)
    clipped_mask[quad_mask] = np.logical_and(nb_V_kept_by_face[quad_mask] < 4,
                                                 nb_V_below_by_face[quad_mask] > 0)

    keepF[clipped_mask] = True
    clipped_faces = np.arange(nf)[clipped_mask]

    nb_kept_F = np.sum(keepF)

    # TODO : etablir ici une connectivite des faces a couper afin d'aider a la projection des vertex sur le plan

    # Initializing the mesh clipping
    nb_new_V = 0
    newV = []
    nb_new_F = 0
    newF = []
    edges = {} # keys are ID of vertices that are above the plane


    # Loop on the faces to clip
    for (iface, face) in enumerate(F[clipped_faces]-1):
        # face is a copy (not a reference) of the line of F
        clipped_face_id = clipped_faces[iface]

        if triangle_mask[clipped_face_id]:
            nb = 3
        else:
            nb = 4

        pos_lst = list(keepV[face[:nb]]) # Ne pas revenir a une liste, tout traiter en numpy !!!
        face_lst = list(face[:nb])

        for iv in range(nb-1, -1, -1):
            # For loop on vertices
            if pos_lst[iv-1] != pos_lst[iv]: # TODO : Gerer les projections ici !!!!
                # We get an edge
                # TODO : mettre un switch pour activer la projection ou pas... --> permettra de merger en meme temps

                iV0 = face_lst[iv-1]
                iV1 = face_lst[iv]
                V0 = V[iV0]
                V1 = V[iV1]

                # Storing the edge and the vertex
                if edges.has_key(iV0):
                    if iV1 not in edges[iV0][0]:
                        # We have to compute the intersection
                        Q = get_edge_intersection_by_plane(plane, V0, V1)
                        nb_new_V += 1
                        newV.append(Q)
                        id_Q = int(nv) + nb_new_V - 1

                        edges[iV0][0].append(iV1)
                        edges[iV0][1].append(id_Q)
                    else:
                        # Intersection has already been calculated
                        id_Q = edges[iV0][1][edges[iV0][0].index(iV1)]
                else:
                    # We have to compute the intersection
                    Q = get_edge_intersection_by_plane(plane, V0, V1)
                    nb_new_V += 1
                    newV.append(Q)
                    id_Q = int(nv) + nb_new_V - 1

                    edges[iV0] = [[iV1], [id_Q]]

                # Here, we know the intersection
                if edges.has_key(iV1):
                    if iV0 not in edges[iV1][0]:
                        edges[iV1][0].append(iV0)
                        edges[iV1][1].append(id_Q)
                else:
                    edges[iV1] = [[iV0], [id_Q]]


                face_lst.insert(iv, id_Q)
                pos_lst.insert(iv, True)

        face_w = np.asarray(face_lst, dtype=np.int32)
        pos = np.asarray(pos_lst, dtype=bool)

        clipped_face = face_w[pos]

        if get_polygon:
            # Storing the boundary edge, making the orientation so that the normals of the final closed polygon will be
            # upward
            for index, ivertex in enumerate(clipped_face):
                if ivertex >= nv:
                    if clipped_face[index-1] >= nv:
                        boundary_edges[ivertex] = clipped_face[index-1]
                    else:
                        boundary_edges[clipped_face[index+1]] = ivertex
                    break

        if len(clipped_face) == 3: # We get a triangle
            clipped_face = np.append(clipped_face, clipped_face[0])

        if len(clipped_face) == 5: # A quad has degenerated in a pentagon, we have to split it in two faces
            n_roll = np.where(pos==False)[0][0]
            clipped_face = np.roll(face_w, -n_roll)

            nb_new_F += 1
            newF.append(clipped_face[quadrangle])

            clipped_face = clipped_face[triangle] # Modified face

        # Updating the initial face with the clipped face
        F[clipped_face_id] = clipped_face + 1 # Staying consistent with what is done in F (indexing starting at 1)

    # Adding new elements to the initial mesh
    if nb_new_V > 0:
        V = np.concatenate((V, np.asarray(newV, dtype=np.float)))
    if nb_new_F > 0:
        F = np.concatenate((F, np.asarray(newF, dtype=np.int32)+1))

    # write_VTU('tests/SEAREV/extended_SEAREV.vtu', V, F)

    extended_nb_V = nv + nb_new_V
    new_nb_V = nb_kept_V + nb_new_V
    new_nb_F = nb_kept_F + nb_new_F

    keepV = np.concatenate((keepV, np.ones(nb_new_V, dtype=bool)))
    keepF = np.concatenate((keepF, np.ones(nb_new_F, dtype=bool)))

    if get_polygon:
        # Computing the boundary curves
        initV = boundary_edges.keys()[0]
        polygons = []
        while len(boundary_edges) > 0:
            polygon = [initV]
            closed = False
            iV = initV
            while not closed:
                iVtarget = boundary_edges.pop(iV)
                polygon.append(iVtarget)
                iV = iVtarget
                if iVtarget == initV:
                    polygons.append(polygon)
                    break

    # Extracting the kept mesh
    clipped_V = V[keepV]
    clipped_F = F[keepF]

    if areas is not None:
        # Computing the new areas for the clipped faces only
        for face in F[clipped_mask]-1:
            print face


    # Upgrading connectivity array with new indexing
    newID_V = np.arange(extended_nb_V)
    newID_V[keepV] = np.arange(new_nb_V)
    clipped_F = newID_V[(F[keepF]-1).flatten()].reshape((new_nb_F, 4))+1

    if get_polygon:
        if areas is not None:
            return clipped_V, clipped_F, polygons, areas
        else:
            return clipped_V, clipped_F, polygons
    else:
        if areas is not None:
            return clipped_V, clipped_F, areas
        else:
            return clipped_V, clipped_F

def get_edge_intersection_by_plane(plane, V0, V1):
    d0 = np.dot(plane.normal, V0) - plane.e
    d1 = np.dot(plane.normal, V1) - plane.e
    t = d0 / (d0-d1)
    return V0+t*(V1-V0)

def get_face_properties(V):
    nv = V.shape[0]
    if nv == 3: # triangle
        normal = np.cross(V[1]-V[0], V[2]-V[0])
        area = np.linag.norm(normal)
        normal /= area
        area /= 2.
        center = np.sum(V, axis=0) / 3.
    else: # quadrangle
        normal = np.cross(V[2]-V[0], V[3]-V[1])
        normal /= np.linalg.norm(normal)
        a1 = np.linalg.norm(np.cross(V[1]-V[0], V[2]-V[0])) / 2.
        a2 = np.linalg.norm(np.cross(V[2]-V[0], V[3]-V[1])) / 2.
        area = a1 + a2
        C1 = np.sum(V[:3], axis=0) / 3.
        C2 = (np.sum(V[2:4], axis=0) + V[0])/ 3. # FIXME : A verifier
        center = (a1*C1 + a2*C2) / area

    # Ne pas oublier de normer la normale

    return area, normal, center

def get_all_faces_properties(V, F):

    nf = F.shape[0]

    F -= 1

    triangle_mask = F[:,0] == F[:,-1]
    nb_triangles = np.sum(triangle_mask)
    quads_mask = np.invert(triangle_mask)
    nb_quads = nf-nb_triangles

    areas = np.zeros(nf, dtype=np.float)
    normals = np.zeros((nf, 3), dtype=np.float)
    centers = np.zeros((nf, 3), dtype=np.float)

    # Collectively dealing with triangles
    triangles = F[triangle_mask]

    triangles_normals = np.cross(V[triangles[:,1]] - V[triangles[:,0]], V[triangles[:,2]] - V[triangles[:,0]])
    triangles_areas = np.linalg.norm(triangles_normals, axis=1)
    normals[triangle_mask] = triangles_normals / np.array(([triangles_areas,]*3)).T
    areas[triangle_mask] = triangles_areas/2.
    centers[triangle_mask] = np.sum(V[triangles[:, :3]], axis=1)/3.

    # Collectively dealing with quads
    quads = F[quads_mask]

    quads_normals = np.cross(V[quads[:,2]] - V[quads[:,0]], V[quads[:,3]] - V[quads[:,1]])
    normals[quads_mask] = quads_normals / np.array(([np.linalg.norm(quads_normals, axis=1),]*3)).T

    a1 = np.linalg.norm(np.cross(V[quads[:,1]] - V[quads[:,0]], V[quads[:,2]] - V[quads[:,0]]), axis=1)/2.
    a2 = np.linalg.norm(np.cross(V[quads[:,3]] - V[quads[:,0]], V[quads[:,2]] - V[quads[:,0]]), axis=1)/2.
    areas[quads_mask] = a1 + a2

    C1 = np.sum(V[quads[:, :3]], axis=1) / 3.
    C2 = (np.sum(V[quads[:, 2:4]], axis=1) + V[quads[:, 0]]) / 3.

    centers[quads_mask] = ( np.array(([a1,]*3)).T * C1 +
          np.array(([a2,]*3)).T * C2 ) /  np.array(([areas[quads_mask],]*3)).T

    # Returning to 1 indexing
    F += 1
    return areas, normals, centers

def heal_normals(V, F, verbose=False): # TODO : mettre le flag a 0 en fin d'implementation

    F -=1

    nv = V.shape[0]
    nf = F.shape[0]

    mesh_closed = True

    # Building connectivities

    # Establishing VV and VF connectivities
    VV = dict([(i, set()) for i in xrange(nv)])
    VF = dict([(i, set()) for i in xrange(nv)])
    for (iface, face) in enumerate(F):
        if face[0] == face[-1]:
            face_w = face[:3]
        else:
            face_w = face
        for (index, iV) in enumerate(face_w):
            VF[iV].add(iface)
            VV[face_w[index-1]].add(iV)
            VV[iV].add(face_w[index-1])

    # Connectivity FF
    FF = dict([(i, set()) for i in xrange(nf)])
    for ivertex in xrange(nv):
        S1 = VF[ivertex]
        for iadjV in VV[ivertex]:
            S2 = VF[iadjV]
            I = list(S1 & S2)
            if len(I) != 1:
                FF[I[0]].add(I[1])
                FF[I[1]].add(I[0])
            else:
                mesh_closed = False

    # Flooding the mesh to find inconsistent normals
    type_cell = np.zeros(nf, dtype=np.int32)
    type_cell[:] = 4
    triangles_mask = F[:,0] == F[:,-1]
    type_cell[triangles_mask] = 3

    FVis = np.zeros(nf, dtype=bool)
    FVis[0] = True
    stack = [0]
    nb_reversed = 0
    while len(stack) > 0:
        iface = stack.pop()
        face = F[iface]
        S1 = set(face)

        for iadjF in FF[iface]:
            if FVis[iadjF]:
                continue
            FVis[iadjF] = True
            # Removing the other pointer
            FF[iadjF].remove(iface) # So as it won't go from iadjF to iface in the future

            # Shared vertices
            adjface = F[iadjF]
            S2 = set(adjface)
            iV1, iV2 = list(S1 & S2)

            # Checking normal consistency
            face_ref = np.roll(face[:type_cell[iface]], -np.where(face == iV1)[0][0])
            adj_face_ref = np.roll(adjface[:type_cell[iadjF]], -np.where(adjface == iV1)[0][0])

            if face_ref[1] == iV2:
                i = 1
            else:
                i = -1

            if adj_face_ref[i] == iV2:
                # Reversing normal
                nb_reversed += 1
                F[iadjF] = np.flipud(F[iadjF])

            # Appending to the stack
            stack.append(iadjF)

    F += 1

    if verbose:
        print '%u faces have been reversed'% nb_reversed


    # Checking if the normals are outgoing
    if mesh_closed:
        zmax = np.max(V[:,2])

        areas, normals, centers = get_all_faces_properties(V, F)

        hs = (np.array([(centers[:, 2]-zmax)*areas,]*3).T * normals).sum(axis=0)

        tol = 1e-9
        if math.fabs(hs[0]) > tol or math.fabs(hs[1]) > tol:
            if verbose:
                print "Warning, the mesh seems not watertight"

        if hs[2] < 0:
            flipped = True
            F = flip_normals(F)
        else:
            flipped = False

        if verbose and flipped:
            print 'normals have been reversed to be outgoing'


    else:
        if verbose:
            #TODO : adding the possibility to plot normals on visualization
            print "Mesh is not closed, meshmagick cannot test if the normals are outgoing. Please consider checking visually (with Paraview by e.g.)"

    return F


def get_volume(V, F):

    return vol

def merge_duplicates(V, F, verbose=False, tol=1e-8):
    """
    Returns a new node array where close nodes have been merged into one node (following tol). It also returns
    the connectivity array F with the new node IDs.
    :param V:
    :param F:
    :param verbose:
    :param tol:
    :return:
    """

    # TODO : Set a tolerance option in command line arguments
    nv, nbdim = V.shape

    levels = [0, nv]
    Vtmp = []
    iperm = np.arange(nv)

    for dim in range(nbdim):
        # Sorting the first dimension
        values = V[:, dim].copy()
        if dim > 0:
            values = values[iperm]
        levels_tmp = []
        for (ilevel, istart) in enumerate(levels[:-1]):
            istop = levels[ilevel+1]

            if istop-istart > 1:
                level_values = values[istart:istop]
                iperm_view = iperm[istart:istop]

                iperm_tmp = level_values.argsort()

                level_values[:] = level_values[iperm_tmp]
                iperm_view[:] = iperm_view[iperm_tmp]

                levels_tmp.append(istart)
                vref = values[istart]

                for idx in xrange(istart, istop):
                    cur_val = values[idx]
                    if np.abs(cur_val - vref) > tol:
                        levels_tmp.append(idx)
                        vref = cur_val

            else:
                levels_tmp.append(levels[ilevel])
        if len(levels_tmp) == nv:
            # No duplicate vertices
            if verbose:  # TODO : verify it with SEAREV mesh
                print "The mesh has no duplicate vertices"
            break

        levels_tmp.append(nv)
        levels = levels_tmp

    else:
        # Building the new merged node list
        Vtmp = []
        newID = np.arange(nv)
        for (ilevel, istart) in enumerate(levels[:-1]):
            istop = levels[ilevel+1]

            Vtmp.append(V[iperm[istart]])
            newID[iperm[range(istart, istop)]] = ilevel
        V = np.array(Vtmp, dtype=float, order='F')
        # Applying renumbering to cells
        for cell in F:
            cell[:] = newID[cell-1]+1

        if verbose:
            nv_new = V.shape[0]
            print "Initial number of nodes : {:d}".format(nv)
            print "New number of nodes     : {:d}".format(nv_new)
            print "{:d} nodes have been merged".format(nv-nv_new)

    return V, F


# =======================================================================
# MESH LOADERS
#=======================================================================
# Contains here all functions to load meshes from different file formats

def load_mesh(filename, format):
    """
    Function to load every known mesh file format
    """
    os.path.isfile(filename)

    if not extension_dict.has_key(format):
        raise IOError, 'Extension ".%s" is not known' % format

    loader = extension_dict[format][0]

    V, F = loader(filename)

    return V, F


def load_RAD(filename):
    """
    Loads RADIOSS files
    :param filename:
    :return:
    """

    import re

    ifile = open(filename, 'r')
    data = ifile.read()
    ifile.close()

    # node_line = r'\s*\d+(?:\s*' + real_str + '){3}'
    node_line = r'\s*\d+\s*(' + real_str + ')\s*(' + real_str + ')\s*(' + real_str + ')'
    node_section = r'((?:' + node_line + ')+)'

    elem_line = r'^\s*(?:\d+\s+){6}\d+\s*[\r\n]+'
    elem_section = r'((?:' + elem_line + '){3,})'

    pattern_node_line = re.compile(node_line, re.MULTILINE)
    pattern_node_line_group = re.compile(node_line, re.MULTILINE)
    pattern_elem_line = re.compile(elem_line, re.MULTILINE)
    pattern_node_section = re.compile(node_section, re.MULTILINE)
    pattern_elem_section = re.compile(elem_section, re.MULTILINE)

    V = []
    node_section = pattern_node_section.search(data).group(1)
    for node in pattern_node_line.finditer(node_section):
        V.append(map(float, list(node.groups())))
    V = np.asarray(V, dtype=float, order='F')

    F = []
    elem_section = pattern_elem_section.search(data).group(1)
    for elem in pattern_elem_line.findall(elem_section):
        F.append(map(int, elem.strip().split()[3:]))
    F = np.asarray(F, dtype=np.int32, order='F')

    return V, F


def load_HST(filename):
    """
    This function loads data from HYDROSTAR software.
    :param filename:
    :return:
    """
    ifile = open(filename, 'r')
    data = ifile.read()
    ifile.close()

    import re

    node_line = r'\s*\d+(?:\s+' + real_str + '){3}'
    node_section = r'((?:' + node_line + ')+)'

    elem_line = r'^\s*(?:\d+\s+){3}\d+\s*[\r\n]+'
    elem_section = r'((?:' + elem_line + ')+)'

    pattern_node_line = re.compile(node_line, re.MULTILINE)
    pattern_elem_line = re.compile(elem_line, re.MULTILINE)
    pattern_node_section = re.compile(node_section, re.MULTILINE)
    pattern_elem_section = re.compile(elem_section, re.MULTILINE)

    Vtmp = []
    nv = 0
    for node_section in pattern_node_section.findall(data):
        for node in pattern_node_line.findall(node_section):
            Vtmp.append(map(float, node.split()[1:]))
        nvtmp = len(Vtmp)
        Vtmp = np.asarray(Vtmp, dtype=float, order='F')
        if nv == 0:
            V = Vtmp.copy()
            nv = nvtmp
        else:
            V = np.concatenate((V, Vtmp))
            nv += nvtmp

    Ftmp = []
    nf = 0
    for elem_section in pattern_elem_section.findall(data):
        for elem in pattern_elem_line.findall(elem_section):
            Ftmp.append(map(int, elem.split()))
        nftmp = len(Ftmp)
        Ftmp = np.asarray(Ftmp, dtype=np.int32, order='F')
        if nf == 0:
            F = Ftmp.copy()
            nf = nftmp
        else:
            F = np.concatenate((F, Ftmp))
            nf += nftmp

    return V, F

def load_DAT(filename):
    raise NotImplementedError

def load_INP(filename):
    """
    This function loads data from DIODORE (PRINCIPIA) INP file format.

    """
    import re

    ifile = open(filename, 'r')
    text = ifile.read()
    ifile.close()

    # Retrieving frames into a dictionnary frames
    pattern_FRAME_str = r'^\s*\*FRAME,NAME=(.+)[\r\n]+(.*)'
    pattern_FRAME = re.compile(pattern_FRAME_str, re.MULTILINE)

    frames = {}
    for match in pattern_FRAME.finditer(text):
        framename = match.group(1).strip()
        framevector = re.split(r'[, ]', match.group(2).strip())
        frames[framename] = np.asarray(map(float, framevector), order='F')

    # Storing the inp layout into a list of dictionnary
    pattern_NODE_ELEMENTS = re.compile(r'^\s*\*(NODE|ELEMENT),(.*)', re.MULTILINE)
    layout = []
    meshfiles = {}
    for match in pattern_NODE_ELEMENTS.finditer(text):
        fielddict = {}
        fielddict['type'] = match.group(1)
        if fielddict['type'] == 'NODE':
            fielddict['INCREMENT'] = 'NO'
        opts = match.group(2).split(',')
        for opt in opts:
            key, pair = opt.split('=')
            fielddict[key] = pair.strip()

        # Retrieving information on meshfiles and their usage
        file = fielddict['INPUT']
        if file in meshfiles:
            meshfiles[file][fielddict['type'] + '_CALL_INP'] += 1
        else:
            meshfiles[file] = {}
            meshfiles[file]['NODE_CALL_INP'] = 0
            meshfiles[file]['ELEMENT_CALL_INP'] = 0
            meshfiles[file][fielddict['type'] + '_CALL_INP'] += 1

        layout.append(fielddict)

        # RETRIEVING DATA SECTIONS FROM MESHFILES
        # patterns for recognition of sections
    node_line = r'\s*\d+(?:\s+' + real_str + '){3}'
    node_section = r'((?:' + node_line + ')+)'
    elem_line = r'^ +\d+(?: +\d+){3,4}[\r\n]+'  # 3 -> triangle, 4 -> quadrangle
    elem_section = r'((?:' + elem_line + ')+)'
    pattern_node_line = re.compile(node_line, re.MULTILINE)
    pattern_elem_line = re.compile(elem_line, re.MULTILINE)
    pattern_node_section = re.compile(node_section, re.MULTILINE)
    pattern_elem_section = re.compile(elem_section, re.MULTILINE)

    for file in meshfiles:
        try:
            meshfile = open(file + '.DAT', 'r')
        except:
            raise IOError, u'File {0:s} not found'.format(file + '.DAT')
        data = meshfile.read()
        meshfile.close()

        node_section = pattern_node_section.findall(data)
        if len(node_section) > 1:
            raise IOError, """Several NODE sections into a .DAT file is not supported by meshmagick
                              as it is considered as bad practice"""
        node_array = []
        idx_array = []
        for node in pattern_node_line.findall(node_section[0]):
            node = node.split()

            node[0] = int(node[0])
            idx_array.append(node[0])
            node[1:] = map(float, node[1:])
            node_array.append(node[1:])

        meshfiles[file]['NODE_SECTION'] = node_array

        # Detecting renumberings to do
        real_idx = 0
        # renumberings = []
        id_new = - np.ones(max(idx_array) + 1, dtype=int)
        for idx in idx_array:
            real_idx += 1
            if real_idx != idx:  # Node number and line number in the array are not consistant...
                id_new[idx] = real_idx

        meshfiles[file]['ELEM_SECTIONS'] = []
        for elem_section in pattern_elem_section.findall(data):

            elem_array = []
            for elem in pattern_elem_line.findall(elem_section):
                elem = map(int, elem.split())
                # for node in elem[1:]:
                elem = id_new[elem[1:]].tolist()
                if len(elem) == 3:  # Case of a triangle, we repeat the first node at the last position
                    elem.append(elem[0])

                elem_array.append(map(int, elem))
            meshfiles[file]['ELEM_SECTIONS'].append(elem_array)
        meshfiles[file]['nb_elem_sections'] = len(meshfiles[file]['ELEM_SECTIONS'])

        meshfiles[file]['nb_elem_sections_used'] = 0

    nbNodes = 0
    nbElems = 0
    for field in layout:
        file = field['INPUT']
        if field['type'] == 'NODE':
            nodes = np.asarray(meshfiles[file]['NODE_SECTION'])
            # Translation of nodes according to frame option id any
            nodes = translate(nodes, frames[field['FRAME']])  # TODO: s'assurer que frame est une options obligatoire...

            if nbNodes == 0:
                V = nodes.copy(order='F')
                nbNodes = V.shape[0]
                increment = False
                continue

            if field['INCREMENT'] == 'NO':
                V[idx, :] = nodes.copy(order='F')
                increment = False
            else:
                V = np.concatenate((V, nodes))
                nbNodes = V.shape[0]
                increment = True
        else:  # this is an ELEMENT section
            elem_section = np.asarray(meshfiles[file]['ELEM_SECTIONS'][meshfiles[file]['nb_elem_sections_used']])

            meshfiles[file]['nb_elem_sections_used'] += 1
            if meshfiles[file]['nb_elem_sections_used'] == meshfiles[file]['nb_elem_sections']:
                meshfiles[file]['nb_elem_sections_used'] = 0

            # Updating to new id of nodes
            elems = elem_section
            if increment:
                elems += nbNodes

            if nbElems == 0:
                F = elems.copy(order='F')
                nbElems = F.shape[0]
                continue
            else:
                F = np.concatenate((F, elems))
                nbElems = F.shape[0]

    return V, F


def load_TEC(filename):
    """
    This function loads data from XML and legacy VTK file format.
    At that time, only unstructured meshes are supported.

    Usage:
        V, F = load_VTK(filename)
    """

    from vtk import vtkTecplotReader

    reader = vtkTecplotReader()

    # Importing the mesh from the file
    reader.SetFileName(filename)
    reader.Update()
    data = reader.GetOutput()

    nv = 0
    nf = 0

    for iblock in range(data.GetNumberOfBlocks()):
        block = data.GetBlock(iblock)
        if block.GetClassName() == 'vtkStructuredGrid':
            continue
        nvblock = block.GetNumberOfPoints()
        nfblock = block.GetNumberOfCells()

        Vtmp = np.zeros((nvblock, 3), dtype=float, order='F')
        for k in range(nvblock):
            Vtmp[k] = np.array(block.GetPoint(k))

        if nv == 0:
            V = Vtmp
        else:
            V = np.concatenate((V, Vtmp))

        nv += nvblock

        # Facet extraction
        Ftmp = np.zeros((nfblock, 4), dtype=np.int32, order='F')
        for k in range(nfblock):
            cell = block.GetCell(k)
            nv_facet = cell.GetNumberOfPoints()
            for l in range(nv_facet):
                Ftmp[k][l] = cell.GetPointId(l)
            if nv_facet == 3:
                Ftmp[k][l] = Ftmp[k][0]

        if nf == 0:
            F = Ftmp
        else:
            F = np.concatenate((F, Ftmp))

        nf += nfblock

    F += 1
    return V, F


def load_VTU(filename):
    """
    This function loads data from XML VTK file format.

    Usage:
        V, F = load_VTU(filename)
    """

    from vtk import vtkXMLUnstructuredGridReader
    reader = vtkXMLUnstructuredGridReader()

    V, F = _load_paraview(filename, reader)
    return V, F


def load_VTK(filename):
    """
    This function loads data from XML and legacy VTK file format.
    At that time, only unstructured meshes are supported.

    Usage:
        V, F = load_VTK(filename)
    """
    from vtk import vtkUnstructuredGridReader
    reader = vtkUnstructuredGridReader()

    V, F = _load_paraview(filename, reader)
    return V, F


def _load_paraview(filename, reader):

    # Importing the mesh from the file
    reader.SetFileName(filename)
    reader.Update()
    vtk_mesh = reader.GetOutput()

    nv = vtk_mesh.GetNumberOfPoints()
    V = np.zeros((nv, 3), dtype=float, order='fortran')
    for k in range(nv):
        V[k] = np.array(vtk_mesh.GetPoint(k))

    nf = vtk_mesh.GetNumberOfCells()
    F = np.zeros((nf, 4), dtype=np.int32, order='fortran')
    for k in range(nf):
        cell = vtk_mesh.GetCell(k)
        nv_facet = cell.GetNumberOfPoints()
        for l in range(nv_facet):
            F[k][l] = cell.GetPointId(l)
        if nv_facet == 3:
            F[k][3] = F[k][0]

    F += 1
    return V, F


def load_STL(filename):
    """
    This function reads an STL file to extract the mesh
    :param filename:
    :return:
    """

    from vtk import vtkSTLReader

    reader = vtkSTLReader()
    reader.SetFileName(filename)
    reader.Update()

    data = reader.GetOutputDataObject(0)

    nv = data.GetNumberOfPoints()
    V = np.zeros((nv, 3), dtype=float, order='F')
    for k in range(nv):
        V[k] = np.array(data.GetPoint(k))
    nf = data.GetNumberOfCells()
    F = np.zeros((nf, 4), dtype=np.int32, order='F')
    for k in range(nf):
        cell = data.GetCell(k)
        if cell is not None:
            for l in range(3):
                F[k][l] = cell.GetPointId(l)
                F[k][3] = F[k][0]  # always repeating the first node as stl is triangle only
    F += 1

    V, F = merge_duplicates(V, F)

    return V, F


def load_NAT(filename):
    """
    This function loads natural file format for meshes.

    Format spec :
    -------------------
    xsym    ysym
    n    m
    x1    y1    z1
    .
    .
    .
    xn    yn    zn
    i1    j1    k1    l1
    .
    .
    .
    im    jm    km    lm
    -------------------

    where :
    n : number of nodes
    m : number of cells
    x1 y1 z1 : cartesian coordinates of node 1
    i1 j1 k1 l1 : counterclock wise Ids of nodes for cell 1
    if cell 1 is a triangle, i1==l1
    """

    ifile = open(filename, 'r')
    xsym, ysym = map(int, ifile.readline().split())
    nv, nf = map(int, ifile.readline().split())

    V = []
    for i in range(nv):
        V.append(map(float, ifile.readline().split()))
    V = np.array(V, dtype=float, order='fortran')

    F = []
    for i in range(nf):
        F.append(map(int, ifile.readline().split()))
    F = np.array(F, dtype=np.int32, order='fortran')

    ifile.close()
    return V, F


def load_GDF(filename):
    """
    This function loads GDF files from WAMIT mesh file format.
    """
    ifile = open(filename, 'r')

    ifile.readline()  # skip one header line
    line = ifile.readline().split()
    ulen = line[0]
    grav = line[1]

    line = ifile.readline().split()
    isx = line[0]
    isy = line[1]

    line = ifile.readline().split()
    nf = int(line[0])

    V = np.zeros((4 * nf, 3), dtype=float, order='fortran')
    F = np.zeros((nf, 4), dtype=np.int32, order='fortran')

    iv = -1
    for icell in range(nf):

        for k in range(4):
            iv += 1
            V[iv, :] = np.array(ifile.readline().split())
            F[icell, k] = iv + 1

    ifile.close()
    V, F = merge_duplicates(V, F, verbose=True)

    return V, F


def load_MAR(filename):
    """
    This function loads .mar files in memory.
    """

    ifile = open(filename, 'r')

    ifile.readline()  # Skipping the first line of the file
    V = []
    while 1:
        line = ifile.readline()
        line = line.split()
        if line[0] == '0':
            break
        V.append(map(float, line[1:]))

    V = np.array(V, dtype=float, order='fortran')
    F = []
    while 1:
        line = ifile.readline()
        line = line.split()
        if line[0] == '0':
            break
        F.append(map(int, line))

    F = np.array(F, dtype=np.int32, order='fortran')

    ifile.close()

    return V, F


def load_STL2(filename):
    import re

    ifile = open(filename, 'r')
    text = ifile.read()
    ifile.close()

    endl = r'(?:\n|\r|\r\n)'
    patt_str = r"""
            ^\s*facet\s+normal(.*)""" + endl + """
            ^\s*outer\sloop""" + endl + """
            ^\s*vertex\s+(.*)""" + endl + """
            ^\s*vertex\s+(.*)""" + endl + """
            ^\s*vertex\s+(.*)""" + endl + """
            ^\s*endloop""" + endl + """
            ^\s*endfacet""" + endl + """
           """
    pattern = re.compile(patt_str, re.MULTILINE | re.VERBOSE)

    normal = []
    V = []
    for match in pattern.finditer(text):
        normal.append(map(float, match.group(1).split()))
        V.append(map(float, match.group(2).split()))
        V.append(map(float, match.group(3).split()))
        V.append(map(float, match.group(4).split()))

    V = np.array(V, dtype=float, order='fortran')

    nf = np.size(V, 0) / 3
    F = np.zeros((nf, 4), dtype=np.int32, order='fortran')

    base = np.array([1, 2, 3, 1])
    for i in range(nf):
        F[i, :] = base + 3 * i

    return V, F


def load_MSH(filename):
    import gmsh

    myMesh = gmsh.Mesh()
    myMesh.read_msh(filename)
    V = np.array(myMesh.Verts, dtype=float, order='fortran')

    ntri = myMesh.nElmts.get(2)
    nquad = myMesh.nElmts.get(3)
    if ntri is None:
        ntri = 0
    if nquad is None:
        nquad = 0

    nel = ntri + nquad

    F = np.zeros((nel, 4), dtype=np.int32, order='fortran')

    if ntri != 0:
        F[:ntri, :3] = myMesh.Elmts.get(2)[1]
        F[:, 3] = F[:, 0]

    if nquad != 0:
        F[ntri:, :] = myMesh.Elmts.get(3)[1]

    F += 1
    return V, F


#=======================================================================
#                             MESH WRITERS
#=======================================================================

def write_mesh(filename, V, F, format):
    """
    This function writes mesh data into filename following its extension
    """

    if not extension_dict.has_key(format):
        raise IOError, 'Extension "%s" is not known' % format

    writer = extension_dict[format][1]

    writer(filename, V, F)


def write_DAT(filename, V, F):
    """
    Writes DAT files for DIODORE
    :param filename:
    :param V:
    :param F:
    :return:
    """

    import time
    import os

    rootfilename, ext = os.path.splitext(filename)
    filename = rootfilename+ext.upper()
    ofile = open(filename, 'w')

    ofile.write('$\n$ Data for DIODORE input file : {0}\n'.format(rootfilename.upper()))
    ofile.write('$ GENERATED BY MESHMAGICK ON {0}\n$\n'.format(time.strftime('%c')))

    ofile.write('$ NODE\n')
    vertex_block = \
        ''.join(
            (
                '\n'.join(
                    ''.join(
                        (
                            '{:8d}'.format(idx+1),
                            ''.join('{:13.5E}'.format(elt) for elt in node)
                        )
                    ) for (idx, node) in enumerate(V)
                ),

                '\n*RETURN\n'
            )
        )
    ofile.write(vertex_block)

    quad_block = '$\n$ ELEMENT,TYPE=Q4C000,ELSTRUCTURE={0}'.format(rootfilename.upper())
    tri_block  = '$\n$ ELEMENT,TYPE=T3C000,ELSTRUCTURE={0}'.format(rootfilename.upper())
    nq = 0
    nt = 0
    for (idx, cell) in enumerate(F):
        if cell[0] != cell[-1]:
            # quadrangle
            nq += 1
            quad_block = ''.join(
                (quad_block,
                 '\n',
                 '{:8d}'.format(idx+1),
                 ''.join('{:8d}'.format(node_id) for node_id in cell)
                )
            )


        else:
            # Triangle
            nt += 1
            tri_block = ''.join(
                (tri_block,
                '\n',
                '{:8d}'.format(idx+1),
                ''.join('{:8d}'.format(node_id) for node_id in cell[:3])
                )
            )

    print '-------------------------------------------------'
    print 'Suggestion for .inp DIODORE input file :'
    print ''
    print '*NODE,INPUT={0},FRAME=???'.format(rootfilename)

    if nq > 0:
        quad_block = ''.join((quad_block, '\n*RETURN\n'))
        ofile.write(quad_block)
        print '*ELEMENT,TYPE=Q4C000,ELSTRUCTURE={0},INPUT={0}'.format(rootfilename)
    if nt > 0:
        tri_block = ''.join((tri_block, '\n*RETURN\n'))
        ofile.write(tri_block)
        print '*ELEMENT,TYPE=T3C000,ELSTRUCTURE={0},INPUT={0}'.format(rootfilename)

    print ''
    print '-------------------------------------------------'
    ofile.close()

    print 'File %s written' % filename

    return


def write_HST(filename, V, F):
    """
    This function writes mesh into a HST file format
    :param filename:
    :param V:
    :param F:
    :return:
    """

    ofile = open(filename, 'w')

    ofile.write(''.join((
        'PROJECT:\n',
        'USERS:   meshmagick\n\n'
        'NBODY   1\n'
        'RHO   1025.0\n'
        'GRAVITY   9.81\n\n'
    )))

    coordinates_block = ''.join((  # block
            'COORDINATES\n',
            '\n'.join(  # line
                ''.join(
                    (
                        '{:10d}'.format(idx+1),  # index
                        ''.join('{:16.6E}'.format(elt) for elt in node)  # node coordinates
                    )
                ) for (idx, node) in enumerate(V)
            ),
            '\nENDCOORDINATES\n\n'
    ))

    ofile.write(coordinates_block)

    cells_coordinates = ''.join((  # block
        'PANEL TYPE 0\n',
        '\n'.join(  # line
            ''.join(
                '{:10d}'.format(node_idx) for node_idx in cell
            ) for cell in F
        ),
        '\nENDPANEL\n\n'
    ))

    ofile.write(cells_coordinates)

    ofile.write('ENDFILE\n')

    ofile.close()

    print u'File {0:s} written'.format(filename)


def write_TEC(filename, V, F):
    """
    This function writes data in a tecplot file

    :param filename:
    :param V:
    :param F:
    :return:
    """
    ofile = open(filename, 'w')

    nv = V.shape[0]
    nf = F.shape[0]

    ofile.write('TITLE = \" THIS FILE WAS GENERATED BY MESHMAGICK - FICHIER : {} \" \n'.format(filename))

    ofile.write('VARIABLES = \"X\",\"Y\",\"Z\" \n')
    ofile.write('ZONE T=\"MESH\" \n')
    ofile.write('N={nv:10d} ,E={nf:10d} ,F=FEPOINT, ET=QUADRILATERAL\n'.format(nv=nv, nf=nf))

    node_block = '\n'.join( # block
        ''.join(
            ''.join('{:16.6E}'.format(elt) for elt in node)
        ) for node in V
    ) + '\n'
    ofile.write(node_block)

    cells_block = '\n'.join(  # block
        ''.join(
            ''.join('{:10d}'.format(node_id) for node_id in cell)
        ) for cell in F
    ) + '\n'
    ofile.write(cells_block)

    ofile.close()
    print 'File %s written' % filename


def write_VTU(filename, V, F):
    from vtk import vtkXMLUnstructuredGridWriter
    writer = vtkXMLUnstructuredGridWriter()
    writer.SetDataModeToAscii()
    _write_paraview(filename, V, F, writer)


def write_VTK(filename, V, F):
    """ This function writes data in a VTK XML file.
    Currently, it only support writing unstructured grids
    """

    from vtk import vtkUnstructuredGridWriter
    writer = vtkUnstructuredGridWriter()
    _write_paraview(filename, V, F, writer)


def _write_paraview(filename, V, F, writer):

    writer.SetFileName(filename)
    vtk_mesh = _build_vtk_mesh_obj(V, F)
    writer.SetInput(vtk_mesh)
    writer.Write()
    print 'File %s written' % filename


def _build_vtk_mesh_obj(V, F):
    import vtk

    nv = max(np.shape(V))
    nf = max(np.shape(F))

    vtk_mesh = vtk.vtkUnstructuredGrid()
    vtk_mesh.Allocate(nf, nf)

    # Building the vtkPoints data structure
    vtk_points = vtk.vtkPoints()
    vtk_points.SetNumberOfPoints(nv)
    idx = -1
    for vertex in V:
        idx += 1
        vtk_points.SetPoint(idx, vertex)

    vtk_mesh.SetPoints(vtk_points)  # Storing the points into vtk_mesh

    # Building the vtkCell data structure
    F = F - 1
    for cell in F:
        if cell[-1] in cell[:-1]:
            vtk_cell = vtk.vtkTriangle()
            nc = 3
        else:
            # #print 'quadrangle'
            vtk_cell = vtk.vtkQuad()
            nc = 4

        for k in range(nc):
            vtk_cell.GetPointIds().SetId(k, cell[k])

        vtk_mesh.InsertNextCell(vtk_cell.GetCellType(), vtk_cell.GetPointIds())
    return vtk_mesh


def write_NAT(filename, V, F, *args):
    """
    This function writes mesh to file
    """
    ofile = open(filename, 'w')

    nv = max(np.shape(V))
    nf = max(np.shape(F))

    ofile.write('%6u%6u\n' % (0, 0))  # lire les symmetries dans args...
    ofile.write('%6u%6u\n' % (nv, nf))
    for vertex in V:
        ofile.write('%15.6E%15.6E%15.6E\n' % (vertex[0], vertex[1], vertex[2]))
    for cell in F:
        ofile.write('%10u%10u%10u%10u\n' % (cell[0], cell[1], cell[2], cell[3]))

    ofile.close()
    print 'File %s written' % filename


def write_GDF(filename, V, F, *args):
    """
    This function writes mesh data into a GDF file for Wamit computations
    """

    nf = max(np.shape(F))

    ofile = open(filename, 'w')

    ofile.write('GDF file generated by meshmagick\n')

    ofile.write('%16.6f%16.6f\n' % (100.0, 9.81))
    ofile.write('%12u%12u\n' % (0, 1))  # TODO : mettre les symetries en argument
    ofile.write('%12u\n' % nf)

    for cell in F:
        for k in range(4):
            Vcur = V[cell[k] - 1, :]
            ofile.write('%16.6E%16.6E%16.6E\n' % (Vcur[0], Vcur[1], Vcur[2]))

    ofile.close()
    print 'File %s written' % filename


def write_MAR(filename, V, F, *args):
    ofile = open(filename, 'w')

    ofile.write('{0:6d}{1:6d}\n'.format(2, 0))  # TODO : mettre les symetries en argument

    nv = V.shape[0]
    for (idx, vertex) in enumerate(V):
        ofile.write('{0:6d}{1:16.6f}{2:16.6f}{3:16.6f}\n'.format(idx+1, vertex[0], vertex[1], vertex[2]))

    ofile.write('{0:6d}{1:6d}{2:6d}{3:6d}{4:6d}\n'.format(0, 0, 0, 0, 0))

    cell_block = '\n'.join(
        ''.join(u'{0:10d}'.format(elt) for elt in cell)
        for cell in F
    ) + '\n'
    ofile.write(cell_block)
    ofile.write('%6u%6u%6u%6u\n' % (0, 0, 0, 0))

    ofile.close()
    print 'File %s written' % filename


def write_STL(filename, V, F):
    """
    :type filename: str
    """

    # TODO : replace this implementation by using the vtk functionalities

    ofile = open(filename, 'w')

    ofile.write('solid meshmagick\n')
    F -= 1  # STL format specifications tells that numerotation starts at 0

    for facet in F:
        if facet[0] != facet[3]:
            raise RuntimeError, 'Only full triangle meshes are accepted in STL files'

        # Computing normal
        v0 = V[facet[0], :]
        v1 = V[facet[1], :]
        v2 = V[facet[2], :]

        n = np.cross(v1 - v0, v2 - v0)
        n /= np.linalg.norm(n)

        block_facet = ''.join(['  facet normal ', ''.join('%15.6e' % ni for ni in n) + '\n',
                               '    outer loop\n',
                               '      vertex', ''.join('%15.6e' % Vi for Vi in v0) + '\n',
                               '      vertex', ''.join('%15.6e' % Vi for Vi in v1) + '\n',
                               '      vertex', ''.join('%15.6e' % Vi for Vi in v2) + '\n',
                               '    endloop\n',
                               '  endfacet\n'])
        ofile.write(block_facet)
    ofile.write('endsolid meshmagick\n')
    ofile.close()

    print 'File %s written' % filename

def write_INP(filename, V, F):
    raise NotImplementedError

def write_MSH(filename, V, F):
    raise NotImplementedError


#=======================================================================
#                         MESH MANIPULATION HELPERS
#=======================================================================
def mesh_quality(V, F):
    # This function is reproduced from
    # http://vtk.org/gitweb?p=VTK.git;a=blob;f=Filters/Verdict/Testing/Python/MeshQuality.py
    import vtk
    import math

    vtk_mesh = _build_vtk_mesh_obj(V, F)
    quality = vtk.vtkMeshQuality()
    quality.SetInput(vtk_mesh)

    def DumpQualityStats(iq, arrayname):
        an = iq.GetOutput().GetFieldData().GetArray(arrayname)
        cardinality = an.GetComponent(0, 4)
        range = list()
        range.append(an.GetComponent(0, 0))
        range.append(an.GetComponent(0, 2))
        average = an.GetComponent(0, 1)
        stdDev = math.sqrt(math.fabs(an.GetComponent(0, 3)))
        outStr = '%s%g%s%g\n%s%g%s%g' % (
                '    range: ', range[0], '  -  ', range[1],
                '    average: ', average, '  , standard deviation: ', stdDev)
        return outStr

    # Here we define the various mesh types and labels for output.
    meshTypes = [
                ['Triangle', 'Triangle',
                 [['QualityMeasureToArea', ' Area Ratio:'],
                  ['QualityMeasureToEdgeRatio', ' Edge Ratio:'],
                  ['QualityMeasureToAspectRatio', ' Aspect Ratio:'],
                  ['QualityMeasureToRadiusRatio', ' Radius Ratio:'],
                  ['QualityMeasureToAspectFrobenius', ' Frobenius Norm:'],
                  ['QualityMeasureToMinAngle', ' Minimal Angle:']
                 ]
                 ],

                ['Quad', 'Quadrilateral',
                 [['QualityMeasureToArea', ' Area Ratio:'],
                  ['QualityMeasureToEdgeRatio', ' Edge Ratio:'],
                  ['QualityMeasureToAspectRatio', ' Aspect Ratio:'],
                  ['QualityMeasureToRadiusRatio', ' Radius Ratio:'],
                  ['QualityMeasureToMedAspectFrobenius',
                  ' Average Frobenius Norm:'],
                  ['QualityMeasureToMaxAspectFrobenius',
                  ' Maximal Frobenius Norm:'],
                  ['QualityMeasureToMinAngle', ' Minimal Angle:']
                 ]
                ]
                ]

    if vtk_mesh.GetNumberOfCells() > 0:
        res = ''
        for meshType in meshTypes:
            res += '\n%s%s' % (meshType[1], ' quality of the mesh ')
            quality.Update()
            an = quality.GetOutput().GetFieldData().GetArray('Mesh ' + meshType[1] + ' Quality')
            cardinality = an.GetComponent(0, 4)

            res = ''.join((res, '(%u elements):\n' % (cardinality)))

            # res += '('+str(cardinality) +meshType[1]+'):\n'

            for measure in meshType[2]:
                eval('quality.Set' + meshType[0] + measure[0] + '()')
                quality.Update()
                res += '\n%s\n%s' % (measure[1],
                        DumpQualityStats(quality,
                                 'Mesh ' + meshType[1] + ' Quality'))
            res += '\n'

    info = """\n\nDefinition of the different quality measures is given
in the verdict library manual :
http://www.vtk.org/Wiki/images/6/6b/VerdictManual-revA.pdf\n"""
    res += info
    return vtk_mesh, res


def get_info(V, F):
    nv = np.size(V, 0)
    nf = np.size(F, 0)
    print ''
    print 'o--------------------------------------------------o'
    print '|               MESH CHARACTERISTICS               |'  #28
    print '|--------------------------------------------------|'
    print '| Number of nodes  :     %15u           |' % nv
    print '|--------------------------------------------------|'
    print '| Number of facets :     %15u           |' % nf
    print '|--------------------------------------------------|'  #51
    print '|      |          Min        |          Max        |'
    print '|------|---------------------|---------------------|'
    print '|   X  |%21E|%21E|' % (V[:, 0].min(), V[:, 0].max())
    print '|------|---------------------|---------------------|'
    print '|   Y  |%21E|%21E|' % (V[:, 1].min(), V[:, 1].max())
    print '|------|---------------------|---------------------|'
    print '|   Z  |%21E|%21E|' % (V[:, 2].min(), V[:, 2].max())
    print 'o--------------------------------------------------o'
    print ''

    _, res = mesh_quality(V, F)
    print res


def translate(V, P):
    """
    Translates an array V with respect to translation vector P.
    :param V:
    :param P:
    :return:
    """

    if not isinstance(P, np.ndarray):
        P = np.asarray(P, dtype=float)

    try:
        for i in range(np.size(V, 0)):
            V[i, :] += P
    except:
        raise RuntimeError, 'second argument must be a 3D list or numpy array for the translation'

    return V


def translate_1D(V, t, ddl):
    if ddl == 'x':
        j = 0
    elif ddl == 'y':
        j = 1
    elif ddl == 'z':
        j = 2
    else:
        raise IOError, "ddl should be chosen among ('x', 'y', 'z')"
    V[:, j] += t
    return V


def rotate(V, rot):
    from math import cos, sin

    if not isinstance(rot, np.ndarray):
        rot = np.asarray(rot, dtype=float)

    R = np.zeros((3, 3), dtype=float, order='f')

    phi = rot[0]
    theta = rot[1]
    psi = rot[2]

    cphi = cos(phi)
    sphi = sin(phi)
    ctheta = cos(theta)
    stheta = sin(theta)
    cpsi = cos(psi)
    spsi = sin(psi)

    R[0, 0] = cpsi * ctheta
    R[0, 1] = -spsi * cphi + cpsi * stheta * sphi
    R[0, 2] = spsi * sphi + cpsi * cphi * stheta
    R[1, 0] = spsi * ctheta
    R[1, 1] = cpsi * cphi + sphi * stheta * spsi
    R[1, 2] = -cpsi * sphi + spsi * cphi * stheta
    R[2, 0] = -stheta
    R[2, 1] = ctheta * sphi
    R[2, 2] = ctheta * cphi

    return np.transpose(np.dot(R, V.T))


def rotate_1D(V, rot, ddl):
    if ddl == 'x':
        j = 0
    elif ddl == 'y':
        j = 1
    elif ddl == 'z':
        j = 2
    else:
        raise IOError, "ddl should be chosen among ('x', 'y', 'z')"

    rotvec = np.zeros(3, dtype=float)
    rotvec[j] = rot
    return rotate(V, rotvec)


def scale(V, alpha):
    return alpha * V


def flip_normals(F):
    return np.fliplr(F)


def symmetrize(V, F, plane):

    # Symmetrizing the nodes
    nv = V.shape[0]

    normal = plane.normal/np.dot(plane.normal, plane.normal)
    V = np.concatenate((V, V-2*np.outer(np.dot(V, normal)-plane.e, normal)))
    F = np.concatenate((F, np.fliplr(F.copy()+nv)))

    return merge_duplicates(V, F, verbose=False)

def show(V, F):
    import vtk

    vtk_mesh = _build_vtk_mesh_obj(V, F)

    surface = vtk.vtkDataSetSurfaceFilter()
    surface.SetInput(vtk_mesh)
    surface.Update()

    mapper = vtk.vtkDataSetMapper()
    mapper.SetInput(surface.GetOutput())

    mesh_actor = vtk.vtkActor()
    mesh_actor.SetMapper(mapper)
    mesh_actor.AddPosition(0, 0, 0)
    mesh_actor.GetProperty().SetColor(1, 1, 0)
    mesh_actor.GetProperty().SetOpacity(1)
    mesh_actor.GetProperty().EdgeVisibilityOn()
    mesh_actor.GetProperty().SetEdgeColor(0, 0, 0)
    mesh_actor.GetProperty().SetLineWidth(1)

    axes_actor = vtk.vtkAxesActor()
    axes = vtk.vtkOrientationMarkerWidget()
    axes.SetOrientationMarker(axes_actor)

    renderer = vtk.vtkRenderer()
    renderer.AddActor(mesh_actor)
    # renderer.AddActor(axes_actor)
    renderer.SetBackground(0.7706, 0.8165, 1.0)

    renderWindow = vtk.vtkRenderWindow()
    renderWindow.AddRenderer(renderer)

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetDesiredUpdateRate(100)
    interactor.SetRenderWindow(renderWindow)

    axes.SetInteractor(interactor)
    axes.EnabledOn()
    axes.InteractiveOn()

    renderWindow.Render()

    interactor.Start()


# =======================================================================
#                         COMMAND LINE USAGE
# =======================================================================
extension_dict = { #keyword           reader,   writer
                  'mar':             (load_MAR, write_MAR),
                  'nemoh':           (load_MAR, write_MAR),
                  'wamit':           (load_GDF, write_GDF),
                  'gdf':             (load_GDF, write_GDF),
                  'diodore-inp':     (load_INP, write_INP),
                  'inp':             (load_INP, write_INP),
                  'diodore-dat':     (load_DAT, write_DAT),
                  'hydrostar':       (load_HST, write_HST),
                  'hst':             (load_HST, write_HST),
                  'natural':         (load_NAT, write_NAT),
                  'nat':             (load_NAT, write_NAT),
                  'gmsh':            (load_MSH, write_MSH),
                  'msh':             (load_MSH, write_MSH),
                  'stl':             (load_STL, write_STL),# FIXME: Verifier que ce n'est pas load_STL2
                  'paraview':        (load_VTU, write_VTU),# VTU
                  'vtu':             (load_VTU, write_VTU),
                  'paraview-legacy': (load_VTK, write_VTK),# VTK
                  'vtk':             (load_VTK, write_VTK),
                  'tecplot':         (load_TEC, write_TEC),
                  'tec':             (load_TEC, write_TEC)
                  }

def main():

    import argparse
    import sys
	
    try:
        import argcomplete

        acok = True
    except:
        acok = False

    parser = argparse.ArgumentParser(
        description="""  --  MESHMAGICK --
                    A python module and a command line utility to manipulate meshes from different
                    format used in hydrodynamics as well as for visualization.

                    The formats currently supported by meshmagick are :

                    *---------------*-------------*-----------------*-----------------------*
                    | File          | R: Reading  | Software        | Keywords              |
                    | extension     | W: writing  |                 |                       |
                    *---------------*-------------*-----------------*-----------------------*
                    |     .mar      |    R/W      | NEMOH (1)       | nemoh, mar            |
                    |     .gdf      |    R/W      | WAMIT (2)       | wamit, gdf            |
                    |     .inp      |    R        | DIODORE (3)     | diodore-inp, inp      |
                    |     .DAT      |    W        | DIODORE (3)     | diodore-dat
                    |     .hst      |    R/W      | HYDROSTAR (4)   | hydrostar, hst        |
                    |     .nat      |    R/W      |    -            | natural, nat          |
                    |     .msh      |    R        | GMSH (5)        | gmsh, msh             |
                    |     .stl      |    R/W      |    -            | stl                   |
                    |     .vtu      |    R/W      | PARAVIEW (6)    | paraview, vtu         |
                    |     .vtk      |    R/W      | PARAVIEW (6)    | paraview-legacy, vtk  |
                    |     .tec      |    R/W      | TECPLOT (7)     | tecplot, tec          |
                    *---------------*-------------------------------------------------------*

                    By default, Meshmagick uses the filename extensions to choose the appropriate
                    reader/writer. This behaviour might be bypassed using the -ifmt and -ofmt
                    optional arguments. When using these options, keywords defined in the table
                    above must be used as format identifiers.

                    (1) NEMOH is an open source BEM Software for seakeeping developped at
                        Ecole Centrale de Nantes (LHHEA)
                    (2) WAMIT is a BEM Software for seakeeping developped by WAMIT, Inc.
                    (3) DIODORE is a BEM Software for seakeeping developped by PRINCIPIA
                    (4) HYDROSTAR is a BEM Software for seakeeping developped by BUREAU VERITAS
                    (5) GMSH is an open source meshing software developped by C. Geuzaine and
                        J.-F. Remacle
                    (6) PARAVIEW is an open source visualization software developped by Kitware
                    (7) TECPLOT is a visualization software developped by Tecplot


                    """,
        epilog='--  Copyright 2014-2015  -  Francois Rongere  /  Ecole Centrale de Nantes  --',
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('infilename',
                        help='path of the input mesh file in any format')

    parser.add_argument('-o', '--outfilename',
                        help='path of the output mesh file. The format of ' +
                             'this file is determined from the extension given')

    parser.add_argument('-ifmt', '--input-format',
                        help="""Input format. Meshmagick will read the input file considering the INPUT_FORMAT rather than using the extension""")

    parser.add_argument('-ofmt', '--output-format',
                        help="""Output format. Meshmagick will write the output file considering the OUTPUT_FORMAT rather than using the extension""")

    parser.add_argument('-v', '--verbose',
                        help="""make the program give more informations on the computations""",
                        action='store_true')

    parser.add_argument('-i', '--info',
                        help="""extract informations on the mesh on the standard output""",
                        action='store_true')

    parser.add_argument('-t', '--translate',
                        nargs=3, type=float,
                        help="""translates the mesh in 3D
                        Usage -translate tx ty tz""")

    parser.add_argument('-tx', '--translatex',
                        nargs=1, type=float,
                        help="""translates the mesh following the x direction""")

    parser.add_argument('-ty', '--translatey',
                        nargs=1, type=float,
                        help="""translates the mesh following the y direction""")

    parser.add_argument('-tz', '--translatez',
                        nargs=1, type=float,
                        help="""translates the mesh following the z direction""")

    parser.add_argument('-r', '--rotate',
                        nargs=3, type=str,
                        help="""rotates the mesh in 3D""")

    parser.add_argument('-rx', '--rotatex',
                        nargs=1, type=str,
                        help="""rotates the mesh around the x direction""")

    parser.add_argument('-ry', '--rotatey',
                        nargs=1, type=str,
                        help="""rotates the mesh around the y direction""")

    parser.add_argument('-rz', '--rotatez',
                        nargs=1, type=str,
                        help="""rotates the mesh around the z direction""")

    parser.add_argument('-s', '--scale',
                        type=float,
                        help="""scales the mesh. CAUTION : if used along
                         with a translation option, the scaling is done before
                        the translations. The translation magnitude should be set
                        accordingly to the newly scaled mesh.""")

    parser.add_argument('-hn', '--heal_normals', action='store_true',
                        help="""Checks and heals the normals consistency and
                        verify if they are outgoing.""")

    parser.add_argument('-fn', '--flip-normals', action='store_true',
                        help="""flips the normals of the mesh""")

    parser.add_argument('-p', '--plane', nargs='+', action='append',
                        help="""Defines a plane used by the --clip and --symmetrize options.
                        It can be defined by the floats nx ny nz c where [nx, ny, nz]
                        is a normal vector to the plane and c defines its position
                        following the equation <N|X> = c with X a point belonging
                        to the plane.
                        It can also be defined by a string among [Oxy, Oxz, Oyz, \Oxy, \Oxz, \Oyz]
                        for quick definition. Several planes may be defined on the same command
                        line. Planes with a prepended '\' have normals inverted i.e. if Oxy has its
                        normal pointing upwards, \Oxy has its normal pointing downwards.
                        In that case, the planes are indexed by an integer starting by
                        0 following the order given in the command line.
                        """)

    parser.add_argument('-clip', '--clip', nargs='*', action='append',
                        help="""cuts the mesh with a plane. Is no arguments are given, the Oxy plane
                        is used. If an integer is given, it should correspond to a plane defined with
                        the --plane option. If a key string is given, it should be a valid key (see
                        help of --plane option for valid plane keys). A normal and a scalar could
                        also be given for the plane definition just as for the --plane option. Several
                        clipping planes may be defined on the same command line.""")

    parser.add_argument('-m', '--merge-duplicates', nargs='?', const='1e-8', default=None,
                        help="""merges the duplicate nodes in the mesh with the absolute tolerance
                        given as argument (default 1e-8)""")

    parser.add_argument('-sym', '--symmetrize', nargs='*', action='append',
                        help="""Symmetrize the mesh by a plane defined wether by 4 scalars, i.e.
                        the plane normal vector coordinates and a scalar c such as N.X=c is the
                        plane equation (with X a point of the plane) or a string among Oxz, Oxy
                        and Oyz which are shortcuts for planes passing by the origin and whose
                        normals are the reference axes. Default is Oxz if only -y is specified.
                        Be careful that symmetry is applied before any rotation so as the plane
                        equation is defined in the initial frame of reference.""")

    parser.add_argument('--show', action='store_true',
                        help="""Shows the input mesh in an interactive window""")

    parser.add_argument('--version', action='version',
                        version='meshmagick - version %s\n%s'%(__version__, __copyright__),
                        help="""Shows the version number and exit""")


    if acok:
        argcomplete.autocomplete(parser)

    # TODO : Utiliser des sous-commandes pour l'utilisation de meshmagick

    args, unknown = parser.parse_known_args()

    write_file = False  # switch to decide if data should be written to outfilename

    # TODO : supprimer le bloc suivant

    # LOADING DATA FROM FILE
    if args.input_format is not None:
        format = args.input_format
    else:
        # Format based on extension
        _ ,ext = os.path.splitext(args.infilename)
        format = ext[1:].lower()
        if format == '':
            raise IOError, 'Unable to determine the input file format from its extension. Please specify an input format.'

    # Loading mesh elements from file
    V, F = load_mesh(args.infilename, format)


    if args.merge_duplicates is not None:
        tol = float(args.merge_duplicates)
        V, F = merge_duplicates(V, F, verbose=args.verbose, tol=tol)
        write_file = True

    if args.heal_normals:
        F = heal_normals(V, F, verbose=args.verbose)


    # TODO : put that dict at the begining of the main function
    plane_str_list = {'Oxy':[0.,0.,1.],
                      'Oxz':[0.,1.,0.],
                      'Oyz':[1.,0.,0.],
                      '\Oxy':[0.,0.,-1.],
                      '\Oxz':[0.,-1.,0.],
                      '\Oyz':[-1.,0.,0.]}

    # Defining planes
    if args.plane is not None:

        nb_planes = len(args.plane)
        planes = [Plane() for i in xrange(nb_planes)]
        for (iplane, plane) in enumerate(args.plane):
            if len(plane) == 4:
                # plane is defined by normal and scalar
                try:
                    planes[iplane].normal = np.array(map(float, plane[:3]), dtype=np.float)
                    planes[iplane].e = float(plane[3])
                except:
                    raise AssertionError, 'Defining a plane by normal and scalar requires four scalars'

            elif len(plane) == 1:
                if plane_str_list.has_key(plane[0]):
                    planes[iplane].normal = np.array(plane_str_list[plane[0]], dtype=np.float)
                    planes[iplane].e = 0.
                else:
                    raise AssertionError, '%s key for plane is not known. Choices are [%s].' % (plane[0], ', '.join(plane_str_list.keys()) )
            else:
                raise AssertionError, 'Planes should be defined by a normal and a scalar or by a key to choose among [%s]' % (', '.join(plane_str_list.keys()))

    # Clipping the mesh
    if args.clip is not None:
        clipping_plane = Plane()
        nb_clip = len(args.clip)
        for plane in args.clip:
            if len(plane) == 0:
                # Default clipping plane Oxy
                clipping_plane.normal = np.array([0., 0., 1.], dtype=np.float)
                clipping_plane.e = 0.
            elif len(plane) == 1:
                try:
                    # Plane ID
                    plane_id = int(plane[0])
                    if plane_id < nb_planes:
                        clipping_plane = planes[plane_id]
                    else:
                        raise AssertionError, 'Plane with ID %u has not been defined with option --plane' % plane_id
                except:
                    # A key string
                    if plane_str_list.has_key(plane[0]):
                        clipping_plane.normal = np.asarray(plane_str_list[plane[0]], dtype=np.float)
                        clipping_plane.e = 0.
                    else:
                        raise AssertionError, 'Planes should be defined by a normal and a scalar or by a key to choose among [%s]' % (', '.join(plane_str_list.keys()))
            elif len(plane) == 4:
                # Plane defined by a normal and a scalar
                try:
                    clipping_plane.normal = np.array(map(float, plane[:3]), dtype=np.float)
                    clipping_plane.e = float(plane[3])
                except:
                    raise AssertionError, 'Defining a plane by normal and scalar requires four scalars'
            else:
                raise AssertionError, 'Unknown mean to define a plane for clipping'
            V, F = clip_by_plane(V, F, clipping_plane)
        write_file = True

    # Symmetrizing the mesh
    if args.symmetrize is not None:
        nb_sym = len(args.symmetrize)
        sym_plane = Plane()
        for plane in args.symmetrize:
            if len(plane) == 0:
                # Default symmetry by plane Oxz
                sym_plane.normal = np.array([0., 1., 0.], dtype=np.float)
                sym_plane.e = 0.
            elif len(plane) == 1:
                try:
                    # Plane ID
                    plane_id = int(plane[0])
                    if plane_id < nb_planes:
                        sym_plane = planes[plane_id]
                    else:
                        raise AssertionError, 'Plane with ID %u has not been defined with option --plane' % plane_id
                except:
                    # A key string
                    if plane_str_list.has_key(plane[0]):
                        sym_plane.normal = np.asarray(plane_str_list[plane[0]], dtype=np.float)
                        sym_plane.e = 0.
                    else:
                        raise AssertionError, 'Planes should be defined by a normal and a scalar or by a key to choose among [%s]' % (', '.join(plane_str_list.keys()))
            elif len(plane) == 4:
                # Plane defined by a normal and a scalar
                try:
                    sym_plane.normal = np.array(map(float, plane[:3]), dtype=np.float)
                    sym_plane.e = float(plane[3])
                except:
                    raise AssertionError, 'Defining a plane by normal and scalar requires four scalars'
            else:
                raise AssertionError, 'Unknown mean to define a plane for symmetry'
            V, F = symmetrize(V, F, sym_plane)
        write_file = True

    # Mesh translations
    if args.translate is not None:
        V = translate(V, args.translate)
        write_file = True
    if args.translatex is not None:
        V = translate_1D(V, args.translatex, 'x')
        write_file = True
    if args.translatey is not None:
        V = translate_1D(V, args.translatey, 'y')
        write_file = True
    if args.translatez is not None:
        V = translate_1D(V, args.translatez, 'z')
        write_file = True

    # Mesh rotations
    # FIXME : supprimer le cast angles et ne prendre que des degres
    if args.rotate is not None:
        args.rotate = cast_angles(args.rotate, args.unit)
        V = rotate(V, args.rotate)
        write_file = True

    if args.rotatex is not None:
        args.rotatex = cast_angles(args.rotatex, args.unit)
        V = rotate_1D(V, args.rotatex[0], 'x')
        write_file = True
    if args.rotatey is not None:
        args.rotatey = cast_angles(args.rotatey, args.unit)
        V = rotate_1D(V, args.rotatey[0], 'y')
        write_file = True
    if args.rotatez is not None:
        args.rotatez = cast_angles(args.rotatez, args.unit)
        V = rotate_1D(V, args.rotatez[0], 'z')
        write_file = True

    if args.scale is not None:
        V = scale(V, args.scale)
        write_file = True

    if args.flip_normals:
        F = flip_normals(F)
        write_file = True

    if args.info:
        get_info(V, F)

    # No more mesh modification should be released from this point -->

    if args.show:
        show(V, F)

    if args.outfilename is None:
        base, ext = os.path.splitext(args.infilename)
        if write_file:
            args.outfilename = '%s_modified%s' % (base, ext)
        # Case where only the output format is given
        if args.output_format is not None:
            write_file = True
            args.outfilename = '%s.%s' % (base, args.output_format)
        # Case where a transformation has been done
    else:
        write_file = True

    # Writing an output file
    if write_file:
        if args.output_format is not None:
            format = args.output_format
        else:
            if args.outfilename is None:
                # We base the output format on the input format used
                if args.input_format is not None:
                    format = args.input_format
                else:
                    format = os.path.splitext(args.infilename)[1][1:].lower()
                    if not extension_dict.has_key(format):
                        raise IOError, 'Could not determine a format from input file extension, please specify an input format or an extension'
            else:
                format = os.path.splitext(args.outfilename)[1][1:].lower()

        write_mesh(args.outfilename, V, F, format)


if __name__ == '__main__':
    main()