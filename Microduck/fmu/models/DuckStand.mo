model DuckStand "Microduck holding the home pose at a chosen servo gain"
  parameter Real gain(unit = "1") = 800 "Position gain register of all servos";
  extends Duck.Examples.Standing(positionGain = gain, checkResults = false, trunkJoint(useQuaternions = false), robot(animation = false));
  Modelica.Blocks.Interfaces.RealOutput z(unit = "m") = trunkHeight "Trunk height";
  Modelica.Blocks.Interfaces.RealOutput pitch(unit = "rad") = trunkPitch "Trunk pitch, nose down positive";
end DuckStand;
