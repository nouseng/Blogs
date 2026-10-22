model WalkNominal
  extends Duck.Examples.WalkingTest(forwardSpeed = 0.3, checkResults = false);
  Real servoTorque[14] = {robot.leftHipYaw.servo.tau, robot.leftHipRoll.servo.tau, robot.leftHipPitch.servo.tau, robot.leftKnee.servo.tau, robot.leftAnkle.servo.tau, robot.neckPitch.servo.tau, robot.headPitch.servo.tau, robot.headYaw.servo.tau, robot.headRoll.servo.tau, robot.rightHipYaw.servo.tau, robot.rightHipRoll.servo.tau, robot.rightHipPitch.servo.tau, robot.rightKnee.servo.tau, robot.rightAnkle.servo.tau} "Servo torque on each joint";
end WalkNominal;
